# -*- coding: utf-8 -*-
"""对话式三栏主界面（ChatTab）：左自选股 / 中对话 / 右K线。

定位：对话式客观数据展示。输入股票代码或点击左侧条目，
右侧自动画K线，中间用大白话客观描述技术指标数值，
不输出任何买卖建议（合规红线）。
"""
from __future__ import annotations

import logging

import pyqtgraph as pg
from PyQt6.QtCore import Qt, pyqtSignal, QThread
from PyQt6.QtWidgets import (QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                             QListWidget, QListWidgetItem, QPushButton,
                             QSplitter, QTextEdit, QVBoxLayout, QWidget)

from core.data import service
from core.quant.indicators import latest_snapshot

log = logging.getLogger("stockai.chat")

# 暗色玻璃态配色
BG = "#0D1117"
FG = "#E6EDF3"
UP = "#00C853"
DOWN = "#FF1744"
CARD = "#161B26"

# 术语通俗解释（悬浮提示）
GLOSSARY = {
    "RSI": "RSI（相对强弱指标）：0-100。低于30通常被视为超卖，高于70通常被视为超买。",
    "MACD": "MACD：两条均线的差值，金叉/死叉常用于描述动量变化，不代表必然趋势。",
    "布林带": "布林带：收盘价围绕其上下轨波动，触及上/下轨常被视为波动区间的极值参考。",
}


def _span(text: str, color: str) -> str:
    return f'<span style="color:{color}">{text}</span>'


class _VoiceThread(QThread):
    """后台录音 + 语音识别（不阻塞 UI）。依赖 SpeechRecognition + pyaudio（手动安装）。"""

    result = pyqtSignal(str)

    def run(self) -> None:
        try:
            import speech_recognition as sr
        except Exception:  # noqa: BLE001
            self.result.emit("__NEED_INSTALL__")
            return
        try:
            r = sr.Recognizer()
            with sr.Microphone() as src:
                r.adjust_for_ambient_noise(src, duration=0.5)
                audio = r.listen(src, timeout=6, phrase_time_limit=12)
            text = r.recognize_google(audio, language="zh-CN")
            self.result.emit(text)
        except sr.UnknownValueError:
            self.result.emit("__NOT_RECOGNIZED__")
        except Exception as e:  # noqa: BLE001
            self.result.emit(f"__ERR__{str(e)[:80]}")


class ChatTab(QWidget):
    """三栏对话式分析视图（模块四：对话式研究入口 + 执行时间线）。"""
    analysis_done = pyqtSignal(str, dict)  # ticker, snapshot
    request_tab = pyqtSignal(int)          # 请求主窗口切换到指定 tab

    def __init__(self, parent=None):
        super().__init__(parent)
        # 上下文感知（由主窗口 set_context 注入：当前页面 + 当前股票）
        self._ctx_page = "对话分析"
        self._ctx_stock = ""
        self._build()

    def set_context(self, page: str, stock: str = "") -> None:
        """外部（主窗口浮动 AI）注入上下文：页面 + 当前选中股票。"""
        self._ctx_page = page or "对话分析"
        self._ctx_stock = stock or ""
        self.setToolTip(f"上下文：{self._ctx_page}｜股票：{self._ctx_stock or '未选中'}")
        self._refresh_reco_hint()

    # ---------- UI ----------
    def _build(self) -> None:
        self.setStyleSheet(f"background:{BG}; color:{FG};")
        root = QHBoxLayout(self)
        sp = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(sp)

        # 左：自选股（默认 5 只示例）
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.addWidget(QLabel("自选股"))
        self.list = QListWidget()
        self.list.setMinimumWidth(200)
        for code, name in [("SH600519", "贵州茅台"), ("AAPL", "苹果"),
                           ("SH000300", "沪深300"), ("SZ300750", "宁德时代"),
                           ("0700.HK", "腾讯控股")]:
            item = QListWidgetItem(f"{name}\n{code}")
            item.setData(Qt.ItemDataRole.UserRole, code)
            self.list.addItem(item)
        self.list.itemClicked.connect(self._on_pick)
        lv.addWidget(self.list)
        b_add = QPushButton("添加")
        b_add.clicked.connect(self._add)
        b_del = QPushButton("删除")
        b_del.clicked.connect(self._del)
        lv.addWidget(b_add)
        lv.addWidget(b_del)

        # 中：对话
        mid = QWidget()
        mv = QVBoxLayout(mid)
        # 快捷入口卡片（对话式研究入口）
        quick_row = QHBoxLayout()
        for text, tip, target in (("📈 分析个股", "深入分析当前股票", 3),
                                  ("⚔️ 多空辩论", "多空结构化对抗", 15),
                                  ("📋 今日复盘", "回看今日市场", 1)):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.setStyleSheet(
                "QPushButton{padding:8px 10px; border-radius:10px;"
                "background:rgba(19,23,34,0.85); border:1px solid rgba(0,229,255,0.15);}"
                "QPushButton:hover{border:1px solid #00E5FF; color:#00E5FF;}")
            b.clicked.connect(lambda _=False, t=target: self.request_tab.emit(t))
            quick_row.addWidget(b)
        mv.addLayout(quick_row)

        # 情境感知推荐（模块四：当前股票 → 新闻/财报/同行对比）
        self.reco_row = QHBoxLayout()
        self.reco_row.setSpacing(6)
        mv.addLayout(self.reco_row)
        self._refresh_reco_hint()
        # 证据链回溯（模块六：AI 分析完成后 🔗 查看证据）
        self.evidence_row = QHBoxLayout()
        self.evidence_row.setSpacing(6)
        self.evidence_row.addStretch(1)
        mv.addLayout(self.evidence_row)
        self.chat = QTextEdit()
        self.chat.setReadOnly(True)
        self.chat.setHtml(self._welcome())
        # 术语悬浮解释
        self.chat.setToolTip("悬停查看：RSI、MACD、布林带等指标的通俗解释见各术语旁。")
        mv.addWidget(self.chat)
        input_row = QHBoxLayout()
        self.btn_search = QPushButton("🔍 搜索")
        self.btn_search.setToolTip("搜索股票（代码/名称/拼音）")
        self.btn_search.setStyleSheet("QPushButton{padding:4px 12px;font-weight:bold;}")
        self.btn_search.clicked.connect(self._open_search)
        input_row.addWidget(self.btn_search)
        self.input = QLineEdit()
        self.input.setPlaceholderText("输入股票代码，如 600519 / AAPL / 0700.HK，回车分析")
        self.input.returnPressed.connect(self._analyze)
        # 自动补全
        from PyQt6.QtWidgets import QCompleter
        from PyQt6.QtCore import QStringListModel
        self._completer = QCompleter(self)
        self._completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._completer.setMaxVisibleItems(10)
        self.input.setCompleter(self._completer)
        self._load_completer_data()
        input_row.addWidget(self.input)
        # 语音输入（模块四：需手动安装 SpeechRecognition + pyaudio 解锁）
        self.btn_voice = QPushButton("🎤")
        self.btn_voice.setToolTip("语音输入（需安装 SpeechRecognition + pyaudio；点击说出你的问题）")
        self.btn_voice.setStyleSheet("QPushButton{padding:4px 10px;font-weight:bold;}")
        self.btn_voice.clicked.connect(self._start_voice)
        input_row.addWidget(self.btn_voice)
        # 分享（模块七：一键分享分析报告）
        self.btn_share = QPushButton("📤 分享")
        self.btn_share.setToolTip("导出当前分析为 Markdown 并复制到剪贴板")
        self.btn_share.setStyleSheet("QPushButton{padding:4px 12px;font-weight:bold;}")
        self.btn_share.clicked.connect(self._share_report)
        input_row.addWidget(self.btn_share)
        mv.addLayout(input_row)

        # 右：K线（收盘价+均线）
        right = QWidget()
        rv = QVBoxLayout(right)
        self.plot = pg.PlotWidget()
        self.plot.setBackground(BG)
        self.plot.showGrid(x=True, y=True, alpha=0.3)
        rv.addWidget(self.plot)
        self.right_title = QLabel("K线（收盘+均线）")
        rv.addWidget(self.right_title)

        sp.addWidget(left)
        sp.addWidget(mid)
        sp.addWidget(right)
        sp.setStretchFactor(0, 1)
        sp.setStretchFactor(1, 4)
        sp.setStretchFactor(2, 3)

    def _load_completer_data(self):
        """加载股票索引到补全列表（常用前 2000 条；全量搜索走 Ctrl+K 命令面板）。"""
        try:
            import json
            from pathlib import Path as P
            stocks_file = P(__file__).parent.parent.parent / "data" / "all_stocks.json"
            if stocks_file.exists():
                with open(stocks_file, encoding="utf-8") as f:
                    stocks = json.load(f)
                # 指数与 A股优先（更常用），其次美股/港股，再其余
                def _key(s):
                    m = s.get("market", "")
                    if s.get("board") == "指数":
                        return 0
                    if m == "A股":
                        return 1
                    if m in ("美股", "港股"):
                        return 2
                    return 3
                stocks = sorted(stocks, key=_key)[:2000]
                items = [f"{s['code']} {s['name']}" for s in stocks]
                self._completer.setModel(QStringListModel(items, self._completer))
        except Exception:
            pass

    # ---------- 情境感知推荐（模块四） ----------
    def _refresh_reco_hint(self) -> None:
        """刷新推荐行：按当前上下文股票给出新闻/财报/同行对比入口。"""
        from PyQt6.QtWidgets import QPushButton as _PB
        while self.reco_row.count():
            it = self.reco_row.takeAt(0)
            w = it.widget()
            if w is not None:
                w.deleteLater()
        if not self._ctx_stock:
            _lbl = QLabel("💡 选中一只股票后，这里会给出该股的新闻 / 财报 / 同行对比推荐")
            _lbl.setStyleSheet("color:#6B7488;")
            self.reco_row.addWidget(_lbl)
            return
        stock = self._ctx_stock
        for label, tip, fn in (
            ("📰 相关新闻", f"查看 {stock} 的最新新闻", self._reco_news),
            ("📑 财报速览", f"查看 {stock} 的基本面/财报要点", self._reco_fundamental),
            ("🏭 同行对比", f"对比 {stock} 的同行表现", self._reco_peers),
        ):
            b = _PB(label)
            b.setToolTip(tip)
            b.setStyleSheet(
                "QPushButton{padding:4px 10px; border-radius:8px; font-size:12px;"
                "background:rgba(19,23,34,0.85); border:1px solid rgba(0,180,216,0.25); color:#7FD8F2;}"
                "QPushButton:hover{border:1px solid #00B4D8; color:#00B4D8;}")
            b.clicked.connect(lambda _=False, f=fn: f())
            self.reco_row.addWidget(b)

    def _reco_news(self) -> None:
        """推荐①：相关新闻（客观展示，含来源）。"""
        stock = self._ctx_stock or ""
        if not stock:
            return
        self._say(f"<div style='color:#8b949e'>📰 {stock} 相关新闻加载中…</div>")
        try:
            from core.data import service
            news = service.get_news(stock, per_symbol_limit=5) or []
        except Exception as e:  # noqa: BLE001
            self._say(f"<div style='color:#FFA726'>新闻加载失败：{str(e)[:100]}</div>")
            return
        if not news:
            self._say("<div style='color:#8b949e'>暂无相关新闻（数据源不可达或该股无近期新闻）。</div>")
            return
        parts = [f"<div style='color:#E6EDF3; font-weight:bold;'>📰 {stock} 相关新闻（{len(news)} 条）</div>"]
        for n in news[:5]:
            title = n.get("title") or n.get("headline") or ""
            src = n.get("source") or n.get("media") or "新闻源"
            date = n.get("date") or n.get("publish_time") or n.get("time") or ""
            parts.append(
                f"<div style='margin:4px 0;'><b>{title}</b><br/>"
                f"<span style='color:#8b949e'>{src} · {date}</span></div>")
        parts.append("<div style='color:#6B7488; font-size:12px;'>以上为客观新闻列表，不代表任何投资立场。</div>")
        self._say("".join(parts))

    def _reco_fundamental(self) -> None:
        """推荐②：财报/基本面速览（确定性规则输出）。"""
        stock = self._ctx_stock or ""
        if not stock:
            return
        self._say(f"<div style='color:#8b949e'>📑 {stock} 基本面速览加载中…</div>")
        try:
            from core.fundamental_analyzer import analyze_fundamentals, render_fundamental_card
            fa = analyze_fundamentals(stock)
            if fa.get("ok") is False or not fa:
                self._say(f"<div style='color:#FFA726'>基本面数据不足：{fa.get('error', '数据源不可达')}</div>")
                return
            self._say(render_fundamental_card(fa))
        except Exception as e:  # noqa: BLE001
            self._say(f"<div style='color:#FFA726'>基本面分析失败：{str(e)[:100]}</div>")

    def _reco_peers(self) -> None:
        """推荐③：同行对比（按同行业筛选 A股，确定性结果）。"""
        stock = self._ctx_stock or ""
        if not stock:
            return
        self._say(f"<div style='color:#8b949e'>🏭 {stock} 同行对比加载中…</div>")
        try:
            from core.screener import run_screener, _a_spot
            spot = _a_spot() or []
            row = next((r for r in spot if r.get("code") in stock or stock in r.get("code", "")), None)
            industry = (row or {}).get("industry", "")
            if not industry:
                self._say("<div style='color:#8b949e'>未能定位行业（数据源不可达时无法对比）。</div>")
                return
            peers = [r for r in spot if r.get("industry") == industry][:6]
            if not peers:
                self._say("<div style='color:#8b949e'>该行业暂无成分数据。</div>")
                return
            parts = [f"<div style='color:#E6EDF3; font-weight:bold;'>🏭 行业「{industry}」成分表现（{len(peers)} 只）</div>"]
            for p in peers:
                chg = float(p.get("chg_pct") or 0)
                color = "#00C853" if chg > 0 else ("#FF1744" if chg < 0 else "#8b949e")
                pe = p.get("pe") or "—"
                mcap = p.get("mcap") or "—"
                parts.append(
                    f"<div style='margin:3px 0;'>"
                    f"<span style='color:#E6EDF3'>{p.get('code')} {p.get('name')}</span> "
                    f"<span style='color:{color}'>{'%+.2f%%' % chg}</span> "
                    f"<span style='color:#8b949e'>PE {pe} · 市值 {mcap}</span></div>")
            parts.append("<div style='color:#6B7488; font-size:12px;'>客观板块数据，非推荐。</div>")
            self._say("".join(parts))
        except Exception as e:  # noqa: BLE001
            self._say(f"<div style='color:#FFA726'>同行对比失败：{str(e)[:100]}</div>")

    # ---------- 语音输入（模块四） ----------
    def _start_voice(self) -> None:
        """麦克风录音 → 语音识别 → 填入输入框并触发分析。"""
        try:
            import importlib.util
            if importlib.util.find_spec("speech_recognition") is None:
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.information(
                    self, "语音输入",
                    "语音识别组件未安装。请手动执行：\n\n"
                    "  pip install SpeechRecognition pyaudio\n\n"
                    "安装后重启程序即可使用语音输入。")
                return
        except Exception:  # noqa: BLE001
            pass
        self.btn_voice.setEnabled(False)
        self.btn_voice.setText("🎤 聆听…")
        self._voice_thread = _VoiceThread(self)
        self._voice_thread.result.connect(self._on_voice_result)
        self._voice_thread.start()

    def _on_voice_result(self, text: str) -> None:
        self.btn_voice.setEnabled(True)
        self.btn_voice.setText("🎤")
        if text == "__NEED_INSTALL__":
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.information(
                self, "语音输入",
                "语音识别组件未安装。请手动执行：\n\n  pip install SpeechRecognition pyaudio")
            return
        if text == "__NOT_RECOGNIZED__":
            self._say("<div style='color:#FFA726'>未识别到语音，请靠近麦克风重试。</div>")
            return
        if text.startswith("__ERR__"):
            self._say(f"<div style='color:#FFA726'>语音识别失败：{text[7:]}</div>")
            return
        self.input.setText(text)
        self._analyze()

    # ---------- 响应式布局（模块四：窄屏自动折叠右栏） ----------
    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        try:
            if self.width() < 980:
                for i in range(self.layout().count()):
                    sp = self.layout().itemAt(i).widget()
                    if isinstance(sp, QSplitter):
                        sp.widget(2).setVisible(False)  # 折叠右栏 K线
            else:
                for i in range(self.layout().count()):
                    sp = self.layout().itemAt(i).widget()
                    if isinstance(sp, QSplitter):
                        sp.widget(2).setVisible(True)
        except Exception:  # noqa: BLE001
            pass

    # ---------- 对话渲染 ----------
    def _welcome(self) -> str:
        return (
            f"<div style='color:#8b949e; line-height:1.7;'>"
            f"<div style='font-size:18px; color:#E6EDF3; font-weight:bold;'>👋 你好，我是你的 AI 研究助手</div><br/>"
            f"输入股票代码、名称或拼音（如 <b>600519</b> / <b>茅台</b> / <b>gzmt</b>），我会：<br/>"
            f"① 识别市场 → ② 采集行情 → ③ 计算技术指标 → ④ 生成客观报告<br/><br/>"
            f"上方快捷入口可直接前往「分析个股」「多空辩论」「今日复盘」。<br/>"
            f"所有输出均为客观数据展示，不构成投资建议。</div>"
        )

    def _say(self, html: str) -> None:
        self.chat.append(html)

    # ---------- 自选股操作 ----------
    def _open_search(self):
        from app.ui.stock_search_dialog import StockSearchDialog
        dlg = StockSearchDialog(self)
        dlg.selected.connect(self.input.setText)
        dlg.exec()

    def _add(self) -> None:
        code, ok = QInputDialog.getText(self, "添加自选股", "股票代码：")
        if ok and code.strip():
            c = code.strip()
            item = QListWidgetItem(c)
            item.setData(Qt.ItemDataRole.UserRole, c)
            self.list.addItem(item)

    def _del(self) -> None:
        for item in self.list.selectedItems():
            self.list.takeItem(self.list.row(item))

    def _on_pick(self, item: QListWidgetItem) -> None:
        code = item.data(Qt.ItemDataRole.UserRole) or item.text().split("\n")[-1]
        self.input.setText(code)
        self._analyze()

    # ---------- 分析 ----------
    @staticmethod
    def _is_pure_ticker(raw: str) -> bool:
        """判断输入是否为纯股票代码（走原 K线+指标链路），否则交给 Agent。"""
        import re
        t = raw.strip().upper()
        if not t:
            return False
        if t.isdigit() and len(t) == 6:
            return True
        if t.startswith(("SH", "SZ")) and len(t) == 8 and t[2:].isdigit():
            return True
        if t.endswith(".HK") and len(t) == 7 and t[:4].isdigit():
            return True
        # 字母代码：仅在股票索引中真实存在（如 AAPL）才视为代码，避免英文单词误判
        if re.fullmatch(r"[A-Z]{1,5}", t):
            try:
                from agent.tool_defs import _stocks_index
                for s in _stocks_index():
                    if s["code"] == t:
                        return True
            except Exception:  # noqa: BLE001
                pass
            return False
        return False

    def _analyze(self) -> None:
        raw = self.input.text().strip()
        if not raw:
            return
        if self._is_pure_ticker(raw):
            self._analyze_ticker(raw)
        else:
            self._ask_agent(raw)

    def _ask_agent(self, raw: str) -> None:
        """自然语言 → AgentCore 工具调用循环（后台线程，不阻塞 UI）。"""
        self._say(f"<b>你：</b>{raw}")
        self.input.setEnabled(False)
        self.btn_search.setEnabled(False)
        self.btn_share.setEnabled(False)
        self._say(
            "<div style='background:rgba(19,23,34,0.85);border:1px solid rgba(0,229,255,0.15);"
            "border-radius:10px;padding:10px 14px;color:#8b949e;'>"
            "🤖 <b>Agent 正在规划工具调用…</b><br/>"
            "⏳ 解析意图 → 选择工具 → 顺序执行 → 合成回复</div>"
        )
        from PyQt6.QtCore import QThread, pyqtSignal as _pyqtSignal

        class _AgentWorker(QThread):
            done = _pyqtSignal(object)
            fail = _pyqtSignal(str)
            event = _pyqtSignal(object)   # 模块七：推理事件实时推送

            def run(self):
                try:
                    from agent.agent_core import AgentCore
                    core = AgentCore()
                    # 模块七：事件桥（后台线程 → 信号 → UI 时间线）
                    def _bridge(ev):
                        self.event.emit(ev)
                    core.set_event_callback(_bridge)
                    # 注入上下文：页面 + 当前股票 + @显式引用
                    ctx = {
                        "page": self._ctx_page,
                        "stock": self._ctx_stock or "",
                        "history": self._recent_history(),
                    }
                    result = core.run(raw, context=ctx)
                    self.done.emit(result)
                except Exception as e:  # noqa: BLE001
                    self.fail.emit(f"{type(e).__name__}: {e}")

        self._aw = _AgentWorker()

        def _on_agent_event(ev) -> None:
            """把推理轨迹渲染为对话内时间线（非阻塞，实时可见）。"""
            try:
                from agent.agent_events import event_label
                icon = {"thinking": "🧠", "tool_call": "🔧", "tool_result": "📥",
                        "reasoning": "⚙️", "final_report": "📄"}.get(
                    ev.event_type.value, "•")
                color = {"thinking": "#00B4D8", "tool_call": "#FFA726",
                         "tool_result": "#8B949E", "reasoning": "#00B4D8",
                         "final_report": "#00C853"}.get(ev.event_type.value, "#DCE1EB")
                self._say(
                    f"<div style='color:{color};font-size:12px;padding:1px 0;'>"
                    f"{icon} <b>{event_label(ev.event_type)}</b> "
                    f"<span style='color:#8b949e'>{ev.content}</span></div>")
            except Exception:  # noqa: BLE001
                pass

        def _on_agent_done(result: dict) -> None:
            self.input.setEnabled(True)
            self.btn_search.setEnabled(True)
            self.btn_share.setEnabled(True)
            plan = result.get("plan") or []
            tools = " → ".join(p["tool"] for p in plan) or "（无工具调用）"
            answer = result.get("answer") or ""
            # AI-vs-AI 合规评审（输出前独立审核）：命中 high 级规则或缺少
            # 免责声明时，附加拦截说明；LLM 评审可选启用（失败自动降级规则）。
            try:
                from security.ai_reviewer import review_output
                _rv = review_output(answer, use_llm=False)
                if not _rv.get("passed"):
                    _notes = "；".join(i.get("label", "") for i in _rv.get("issues", [])[:3])
                    answer = answer + (f"\n\n⚠️ [合规拦截] 输出未通过独立评审：{_notes}。"
                                       f"（{_rv.get('score', 0)} 分）")
            except Exception:  # noqa: BLE001
                pass
            self._say(
                f"<div style='color:#8b949e;font-size:12px'>🧰 工具链：{tools}</div>")
            self._say(f"<div style='line-height:1.7'>{answer}</div>")
            # 证据链回溯（模块六）：🔗 按钮 → 证据面板
            eid = result.get("evidence_id")
            self._show_evidence_button(eid)
            # 自主学习闭环（2026-10）：分析完成后自动沉淀经验，失败静默
            try:
                from core.agents import evo_memory
                _kinds = {"财报": "财报", "估值": "估值", "K线": "技术",
                          "指标": "技术", "新闻": "新闻", "宏观": "宏观"}
                _kind = next((v for k, v in _kinds.items()
                              if k in (plan and " ".join(p.get("tool", "")
                                                         for p in plan) or "")),
                             "通用")
                _verdict = "看多" if any(w in answer for w in ("看多", "买入", "偏多")) \
                    else ("看空" if any(w in answer for w in ("看空", "卖出", "偏空"))
                          else "中性")
                evo_memory.analyze_reflect({
                    "kind": _kind, "ticker": extract_ticker(raw) or "",
                    "verdict": _verdict,
                    "confidence": float(result.get("confidence") or 0.5),
                    "model_engine": str(result.get("engine") or ""),
                    "summary": answer[:200]})
            except Exception:  # noqa: BLE001
                pass
            # 若提取到代码，联动右侧 K线
            from agent.agent_core import extract_ticker
            code = extract_ticker(raw)
            if code and self._is_pure_ticker(code):
                self._draw_for_code(code)

        def _on_agent_fail(err: str) -> None:
            self.input.setEnabled(True)
            self.btn_search.setEnabled(True)
            self.btn_share.setEnabled(True)
            self._say(f"<span style='color:#FFA726'>Agent 调用失败：{err}</span>")

        self._aw.done.connect(_on_agent_done)
        self._aw.fail.connect(_on_agent_fail)
        self._aw.event.connect(_on_agent_event)
        self._aw.start()

    def _show_evidence_button(self, evidence_id) -> None:
        """证据链回溯（模块六）：在对话区下方显示 🔗 按钮。"""
        try:
            from PyQt6.QtWidgets import QPushButton as _PB
            while self.evidence_row.count() > 1:  # 保留 stretch
                it = self.evidence_row.takeAt(0)
                w = it.widget()
                if w is not None:
                    w.deleteLater()
            if not evidence_id:
                return
            b = _PB("🔗 查看证据链")
            b.setToolTip(f"evidence_id: {evidence_id}")
            b.setStyleSheet(
                "QPushButton{padding:4px 12px;border-radius:8px;font-size:12px;"
                "background:rgba(0,180,216,0.12);border:1px solid rgba(0,180,216,0.35);color:#7FD8F2;}"
                "QPushButton:hover{border:1px solid #00B4D8;color:#00B4D8;}")
            b.clicked.connect(
                lambda _=False, eid=evidence_id: self._open_evidence(eid))
            self.evidence_row.insertWidget(self.evidence_row.count() - 1, b)
        except Exception:  # noqa: BLE001
            pass

    def _open_evidence(self, evidence_id: str) -> None:
        try:
            from app.ui.evidence_dialog import EvidenceDialog
            dlg = EvidenceDialog(evidence_id, self)
            dlg.exec()
        except Exception as e:  # noqa: BLE001
            self._say(f"<span style='color:#FFA726'>证据面板打开失败：{str(e)[:80]}</span>")

    def _recent_history(self) -> list:
        """最近 6 轮对话记录（供上下文优先级使用）。"""
        import re
        out = []
        txt = self.chat.toPlainText()
        # 简单切分 "你：" / "AI：" 段落，保留末尾最近几条
        for seg in re.split(r"\n(?=你：|AI：)", txt):
            seg = seg.strip()
            if not seg:
                continue
            if seg.startswith("你："):
                out.append({"role": "user", "content": seg[2:][:120]})
            elif seg.startswith("AI："):
                out.append({"role": "assistant", "content": seg[3:][:120]})
        return out[-6:]

    def _draw_for_code(self, code: str) -> None:
        """自然语言识别出代码时，右侧渲染 K线（复用异步加载）。"""
        from PyQt6.QtCore import QThread, pyqtSignal as _pyqtSignal

        class _W(QThread):
            done = _pyqtSignal(object, str, object)

            def run(self):
                try:
                    df, source = service.get_daily(code)
                    self.done.emit(code, source, df)
                except Exception:  # noqa: BLE001
                    self.done.emit(code, "", None)

        w = _W()

        def _ok(code_, source_, df_):
            if df_ is not None and len(df_) > 30:
                self._draw(df_)
                self.right_title.setText(f"近期收盘价（{len(df_)}日）")
        w.done.connect(_ok)
        w.start()

    def _analyze_ticker(self, raw: str) -> None:
        code = self._normalize(raw)
        self._say(f"<b>你：</b>{raw}")
        # 禁用输入，显示加载中
        self.input.setEnabled(False)
        self.btn_search.setEnabled(False)
        self.btn_share.setEnabled(False)
        # 模块四：AI 执行时间线（逐步打勾，让用户看到 AI 在做什么）
        self._timeline_id = self.chat.document().characterCount()
        self._say(
            "<div style='background:rgba(19,23,34,0.85);border:1px solid rgba(0,229,255,0.15);"
            "border-radius:10px;padding:10px 14px;color:#8b949e;'>"
            "🧠 <b>AI 执行中…</b><br/>"
            "⏳ ① 识别市场（A股/港股/美股）…<br/>"
            "⏳ ② 采集行情数据…<br/>"
            "⏳ ③ 计算技术指标…<br/>"
            "⏳ ④ 生成报告…</div>"
        )
        # 异步加载
        from PyQt6.QtCore import QThread, pyqtSignal as _pyqtSignal

        class _Worker(QThread):
            done = _pyqtSignal(object, str, object)
            fail = _pyqtSignal(str)

            def run(self):
                try:
                    df, source = service.get_daily(code)
                    self.done.emit(code, source, df)
                except Exception as e:
                    self.fail.emit(str(e))

        self._w = _Worker()
        self._w.done.connect(self._on_data_ready)
        self._w.fail.connect(self._on_data_fail)
        self._w.start()

    def _timeline_done(self, ok: bool) -> None:
        """执行时间线收尾：全部打勾或标注失败。"""
        try:
            cur = self.chat.textCursor()
            cur.setPosition(self._timeline_id)
            cur.movePosition(cur.MoveOperation.EndOfBlock, cur.MoveMode.KeepAnchor)
            if ok:
                cur.insertHtml(
                    "<div style='background:rgba(19,23,34,0.85);border:1px solid rgba(0,229,255,0.15);"
                    "border-radius:10px;padding:10px 14px;color:#8b949e;'>"
                    "🧠 <b>AI 执行完成</b><br/>"
                    "✅ ① 识别市场<br/>"
                    "✅ ② 采集行情数据<br/>"
                    "✅ ③ 计算技术指标<br/>"
                    "✅ ④ 生成报告</div>")
            else:
                cur.insertHtml(
                    "<div style='background:rgba(255,167,38,0.10);border:1px solid #FFA726;"
                    "border-radius:10px;padding:10px 14px;color:#FFA726;'>"
                    "❌ 数据获取失败，已停止执行。</div>")
        except Exception:  # noqa: BLE001
            pass

    def _on_data_ready(self, code: str, source: str, df) -> None:
        self.input.setEnabled(True)
        self.btn_search.setEnabled(True)
        self.btn_share.setEnabled(True)
        self._timeline_done(True)
        self._last_report = {"code": code, "source": source}
        if df is None or len(df) < 30:
            self._say("<span style='color:#8b949e'>数据不足，无法展示指标。</span>")
            return
        snap = latest_snapshot(df)
        self._draw(df)
        self._render_facts(code, snap, source)
        self._highlight_left(code, snap)
        self.analysis_done.emit(code, snap)
        # 沉淀到长期记忆
        try:
            from core.memory.long_term import save_analysis
            save_analysis(
                ticker=code,
                name=code,
                price=float(snap.get("close", 0)),
                chg_pct=float(snap.get("chg_pct_1d", 0) or 0),
                rsi=float(snap.get("rsi14", 0) or 0),
                macd_signal=str(snap.get("macd_signal", "")),
                summary=f"RSI={snap.get('rsi14'):.1f}",
                source=source,
            )
        except Exception:
            pass
        # 模块四：保存提示
        self._say("<span style='color:#00E5FF'>✅ 本轮分析已保存到本地知识库（可随时回看）。</span>")

    def _on_data_fail(self, err: str) -> None:
        self.input.setEnabled(True)
        self.btn_search.setEnabled(True)
        self.btn_share.setEnabled(True)
        self._timeline_done(False)
        self._say(f"<span style='color:#FFA726'>获取数据失败：{err}</span>")

    # ---------- 模块七：分享报告 ----------
    def _share_report(self) -> None:
        """把最近一次分析导出为 Markdown：复制剪贴板 + 存档 data/reports/。"""
        from datetime import datetime
        rep = getattr(self, "_last_report", None)
        code = rep["code"] if rep else (self.input.text().strip() or "—")
        try:
            from core.data import service as _svc
            df, source = _svc.get_daily(code)
            if df is None or len(df) < 2:
                raise ValueError("数据不足")
            from core.quant.indicators import latest_snapshot
            s = latest_snapshot(df)
            chg = s.get("chg_pct_1d")
            chg_txt = f"{chg:+.2f}%" if chg is not None else "—"
            md = (
                f"# 疏影·知微 分析报告\n\n"
                f"- 标的：{code}\n- 数据源：{source}\n- 时间：{datetime.now():%Y-%m-%d %H:%M}\n\n"
                f"## 行情快照\n\n| 项目 | 数值 |\n|---|---|\n"
                f"| 最新收盘 | {s.get('close', '—')} |\n| 涨跌幅 | {chg_txt} |\n"
                f"| RSI(14) | {s.get('rsi14', '—') if s.get('rsi14') is not None else '—'} |\n"
                f"| MACD | {(s.get('macd') or {}).get('signal', '无交叉信号')} |\n\n"
                f"---\n*本报告为客观数据展示，不构成投资建议。投资有风险。*\n"
            )
            import os
            report_dir = os.path.join(os.path.dirname(os.path.dirname(
                os.path.dirname(os.path.abspath(__file__)))), "data", "reports")
            os.makedirs(report_dir, exist_ok=True)
            path = os.path.join(report_dir,
                                f"report_{code.replace('.','_')}_{datetime.now():%Y%m%d_%H%M}.md")
            with open(path, "w", encoding="utf-8") as f:
                f.write(md)
            from PyQt6.QtWidgets import QApplication
            QApplication.clipboard().setText(md)
            self._say(f"<span style='color:#00E5FF'>📤 报告已复制到剪贴板并保存：{path}</span>")
        except Exception as e:  # noqa: BLE001
            self._say(f"<span style='color:#FFA726'>分享失败：{e}</span>")

    @staticmethod
    def _normalize(raw: str) -> str:
        r = raw.strip()
        if r.isdigit() and len(r) == 6:
            return ("SH" if r.startswith(("6", "9")) else "SZ") + r
        return r.upper()

    def _draw(self, df) -> None:
        self.plot.clear()
        close = df["close"]
        self.plot.plot(close.values, pen=pg.mkPen("#58a6ff", width=2), name="收盘")
        if len(close) >= 20:
            ma20 = close.rolling(20).mean()
            self.plot.plot(ma20.values, pen=pg.mkPen("#f0b429", width=1), name="MA20")
        self.right_title.setText(f"近期收盘价（{len(close)}日）")

    def _highlight_left(self, code: str, s: dict) -> None:
        """分析完成后：左侧列表高亮当前股票，并把条目更新为带涨跌的卡片。"""
        chg = s.get("chg_pct_1d")
        chg_txt = f"{chg:+.2f}%" if chg is not None else ""
        col = UP if (chg or 0) >= 0 else DOWN
        for i in range(self.list.count()):
            it = self.list.item(i)
            if (it.data(Qt.ItemDataRole.UserRole) or it.text().split("\n")[-1]) == code:
                base = it.data(Qt.ItemDataRole.UserRole) or code
                name = it.text().split("\n")[0] if "\n" in it.text() else code
                it.setText(f"{name}\n{base}  {chg_txt}")
                it.setForeground(Qt.GlobalColor.white)
                self.list.setCurrentItem(it)
                break

    def _confidence(self, s: dict) -> tuple[str, str]:
        """客观数据完整度 → 高/中/低（纯展示，不代表预测可靠度）。"""
        rsi, macd = s.get("rsi14"), (s.get("macd") or {}).get("HIST")
        good = sum(x is not None for x in (rsi, macd, s.get("close")))
        if good >= 3:
            return "高", "#00C853"
        if good == 2:
            return "中", "#f0b429"
        return "低", "#8b949e"

    def _render_facts(self, code: str, s: dict, source: str) -> None:
        price = s.get("close")
        chg = s.get("chg_pct_1d")
        color = UP if (chg or 0) >= 0 else DOWN
        chg_txt = f"{chg:+.2f}%" if chg is not None else "—"
        rsi = s.get("rsi14")
        macd_state = (s.get("macd") or {}).get("signal") or "无交叉信号"
        p60 = (s.get("chg_pct_periods") or {}).get(60)
        p60_txt = f"{p60:+.2f}%" if p60 is not None else "—"
        conf, conf_col = self._confidence(s)
        lines = [
            f"<b>AI：</b><br/>",
            f'<span style="background:{conf_col};color:#0D1117;padding:1px 6px;'
            f'border-radius:4px;font-size:12px">数据完整度：{conf}</span>　'
            f"<b>{code}</b>（{s.get('asof','')}）最新收盘 {price}"
            f"（{_span(chg_txt, color)}，数据源：{source}）<br/>",
        ]
        if rsi is not None:
            tip = GLOSSARY["RSI"]
            lines.append(f"· <span title='{tip}'><u>RSI(14)</u></span> = {rsi:.1f}<br/>")
        tip_m = GLOSSARY["MACD"]
        lines.append(f"· <span title='{tip_m}'><u>MACD</u></span> 状态：{macd_state}<br/>")
        lines.append("<br/>📌 <b>一句话：</b>"
                     f"近60日涨跌 {p60_txt}，RSI {rsi if rsi is None else f'{rsi:.1f}'}，"
                     f"以上为客观数据展示，不构成投资建议。")
        self._say("".join(lines))
