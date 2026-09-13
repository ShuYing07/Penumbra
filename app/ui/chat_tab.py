# -*- coding: utf-8 -*-
"""对话式三栏主界面（ChatTab）：左自选股 / 中对话 / 右K线。

定位：对话式客观数据展示。输入股票代码或点击左侧条目，
右侧自动画K线，中间用大白话客观描述技术指标数值，
不输出任何买卖建议（合规红线）。
"""
from __future__ import annotations

import logging

import pyqtgraph as pg
from PyQt6.QtCore import Qt
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


class ChatTab(QWidget):
    """三栏对话式分析视图。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build()

    # ---------- UI ----------
    def _build(self) -> None:
        self.setStyleSheet(f"background:{BG}; color:{FG};")
        root = QHBoxLayout(self)
        sp = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(sp)

        # 左：自选股
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.addWidget(QLabel("自选股"))
        self.list = QListWidget()
        self.list.setMinimumWidth(200)
        for code, name in [("SH600519", "贵州茅台"), ("AAPL", "苹果"),
                           ("SH000300", "沪深300"), ("SZ300750", "宁德时代")]:
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
        self.chat = QTextEdit()
        self.chat.setReadOnly(True)
        self.chat.setHtml(self._welcome())
        # 术语悬浮解释
        self.chat.setToolTip("悬停查看：RSI、MACD、布林带等指标的通俗解释见各术语旁。")
        mv.addWidget(self.chat)
        self.input = QLineEdit()
        self.input.setPlaceholderText("输入股票代码，如 600519 / SH600519 / AAPL，回车分析")
        self.input.returnPressed.connect(self._analyze)
        mv.addWidget(self.input)

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

    # ---------- 对话渲染 ----------
    def _welcome(self) -> str:
        return (
            f"<div style='color:#8b949e'>👋 你好！在下方输入框输入股票代码（如 "
            f"贵州茅台或 600519），我会客观展示它的行情与技术指标。<br>"
            f"试试输入「贵州茅台」或「600519」开始分析。</div>"
        )

    def _say(self, html: str) -> None:
        self.chat.append(html)

    # ---------- 自选股操作 ----------
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
    def _analyze(self) -> None:
        raw = self.input.text().strip()
        if not raw:
            return
        code = self._normalize(raw)
        self._say(f"<b>你：</b>{raw}")
        try:
            df, source = service.get_daily(code)
        except Exception as e:  # noqa: BLE001
            self._say(f"<span style='color:#FF1744'>获取数据失败：{e}</span>")
            return
        if df is None or len(df) < 30:
            self._say("<span style='color:#8b949e'>数据不足，无法展示指标。</span>")
            return
        snap = latest_snapshot(df)
        self._draw(df)
        self._render_facts(code, snap, source)
        self._highlight_left(code, snap)

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
