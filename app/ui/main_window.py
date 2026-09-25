# -*- coding: utf-8 -*-
"""主窗口：三栏布局（左侧导航 + 中央工作区 + 右侧信息面板）。"""
from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer, QSize, QThread, pyqtSignal
from PyQt6.QtGui import QIcon, QAction, QKeySequence, QShortcut
from PyQt6.QtWidgets import (QLabel, QMainWindow, QStatusBar, QStyle, QSystemTrayIcon,
                             QTabWidget, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                             QMessageBox, QTextEdit, QComboBox, QSplitter, QListWidget,
                             QListWidgetItem, QStackedWidget, QFrame, QSizePolicy)

from app.ui.analysis_tab import AnalysisTab
from app.ui.analysis_log_tab import AnalysisLogTab
from app.ui.compliance_audit_tab import ComplianceAuditTab
from app.ui.backtest_tab import BacktestTab
from app.ui.chat_tab import ChatTab
from app.ui.debate_tab import DebateTab
from app.ui.chart_tab import ChartTab
from app.ui.history_tab import HistoryTab
from app.ui.industry_tab import IndustryTab
from app.ui.knowledge_tab import KnowledgeTab
from app.ui.optimize_tab import OptimizeTab
from app.ui.overview_tab import OverviewTab
from app.ui.paper_tab import PaperTab
from app.ui.portfolio_tab import PortfolioTab
from app.ui.replay_tab import ReplayTab
from app.ui.watchlist_tab import WatchlistTab
from app.ui.stock_directory_tab import StockDirectoryTab
from app.ui.ui_theme import (BG_CARD, BORDER, TEXT_MAIN, TEXT_SUB, ACCENT,
                            UP, DOWN, WARN, BG_HOVER)
from config_manager import is_dev_mode
from core.config import DISCLAIMER, DATA_DIR


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("疏影 · 知微")
        self.resize(1200, 800)
        # 恢复窗口位置（如果上次保存过）
        from PyQt6.QtCore import QSettings
        from PyQt6.QtGui import QGuiApplication
        settings = QSettings("Shuying", "ShuyingInsight")
        geom = settings.value("geometry")
        if geom:
            self.restoreGeometry(geom)
        else:
            # 首次启动居中
            screen = QGuiApplication.primaryScreen().availableGeometry()
            self.move(
                (screen.width() - self.width()) // 2,
                (screen.height() - self.height()) // 2,
            )
        # 校验窗口在屏幕内
        self._ensure_on_screen()
        import os as _os, sys as _sys
        _cands = []
        _mp = getattr(_sys, "_MEIPASS", None)
        if _mp:
            _cands.append(_os.path.join(_mp, "assets", "app.ico"))
        _cands.append(_os.path.join(_os.path.dirname(_os.path.dirname(_os.path.dirname(
            _os.path.abspath(__file__)))), "assets", "app.ico"))
        for _ico in _cands:
            if _os.path.exists(_ico):
                self.setWindowIcon(QIcon(_ico))
                break

        # 首屏只创建必要tab，其他懒加载
        self.chat_tab = ChatTab()
        self.chat_tab.analysis_done.connect(self._on_chat_analysis)
        self.overview_tab = OverviewTab()
        self.watchlist_tab = WatchlistTab()
        self.analysis_tab = AnalysisTab()
        self.chart_tab = ChartTab()
        # 延迟创建的tab
        self._lazy_tabs = {
            5: ("模拟盘", PaperTab),
            6: ("回测", BacktestTab),
            7: ("组合回测", PortfolioTab),
            8: ("参数寻优", OptimizeTab),
            9: ("信号回放", ReplayTab),
            10: ("学习库", KnowledgeTab),
            11: ("决策记录", HistoryTab),
            12: ("分析日志", AnalysisLogTab),
            13: ("合规审计", ComplianceAuditTab),
            14: ("产业图谱", IndustryTab),
            15: ("多空辩论", DebateTab),
            16: ("股票大全", StockDirectoryTab),
        }
        self._created = {}

        # 中央标签页
        self.tabs = QTabWidget()
        self.tabs.addTab(self.chat_tab, "对话分析")
        self.tabs.addTab(self.overview_tab, "市场概览")
        self.tabs.addTab(self.watchlist_tab, "自选股")
        self.tabs.addTab(self.analysis_tab, "分析")
        self.tabs.addTab(self.chart_tab, "K线图")
        for i in range(5, 17):
            name, _ = self._lazy_tabs[i]
            self.tabs.addTab(QWidget(), name)
        self.tabs.currentChanged.connect(self._on_tab_changed)

        # 确保数据库表初始化
        try:
            from core.memory.decision_log import init as _dl_init
            _dl_init()
        except Exception:
            pass

        # 隐藏顶部tab栏，只通过左侧导航切换
        self.tabs.tabBar().hide()

        # 开发者调试面板
        if is_dev_mode():
            self.tabs.addTab(self._build_debug_panel(), "开发者工具")

        # 三栏布局
        left_panel = self._build_left_panel()
        right_panel = self._build_right_panel()

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left_panel)
        splitter.addWidget(self.tabs)
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        splitter.setSizes([220, 900, 300])
        splitter.setCollapsible(0, False)
        splitter.setCollapsible(2, False)
        self.setCentralWidget(splitter)

        sb = QStatusBar()
        sb.addWidget(QLabel("⚠️ 本工具仅供研究学习，不构成投资建议"))
        sb.addPermanentWidget(QLabel("    "))
        sponsor_btn = QPushButton("❤️ 支持开发者")
        sponsor_btn.setStyleSheet(
            "background-color:#2F81F7; color:white; border-radius:5px; padding:5px 10px;"
        )
        sponsor_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        sponsor_btn.clicked.connect(self._open_sponsor)
        sb.addPermanentWidget(sponsor_btn)
        sb.addPermanentWidget(QLabel("您的支持是我持续更新的动力 🙏"))
        self.setStatusBar(sb)

        # 系统托盘（offscreen / 无桌面环境时不可用，跳过且不影响主流程）
        self.tray: QSystemTrayIcon | None = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = QSystemTrayIcon(
                self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon), self)
            self.tray.setToolTip("疏影 · 知微 盯盘")
            self.tray.messageClicked.connect(self.showNormal)
            self.tray.show()

        # 联动：分析完成 → 刷新决策记录 / K线图自动载入 / 模拟盘刷新
        self.analysis_tab.analysis_finished.connect(self._on_analysis_done)
        # 用户输入代码后立即加载K线（不等AI分析，数据层独立）
        self.analysis_tab.ticker_submitted.connect(self.chart_tab.load)
        # 自选股 → 加入分析（双击/右键）
        self.watchlist_tab.analyze_requested.connect(self._on_watchlist_analyze)
        # 自选股触发 → 托盘气泡通知
        self.watchlist_tab.triggered.connect(self._on_watchlist_triggered)

        # 帮助菜单：意见反馈（不收集数据，跳转 GitHub Issues）
        bar = self.menuBar()
        help_menu = bar.addMenu("帮助")
        help_menu.addAction("意见反馈", self._open_feedback)
        help_menu.addAction("API 设置", self._open_api_settings)
        help_menu.addAction("检查更新", self._check_update)
        help_menu.addAction("❤️ 支持开发者", self._open_sponsor)

        # 启动公告：延迟弹出，提示用户去 GitHub 查看最新版本
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(600, self._show_announcement)
        QTimer.singleShot(1500, self._load_market_overview)
        # 首次启动自动加载示例股票
        QTimer.singleShot(2000, self._load_demo)
        # 每30秒刷新市场概览
        self._mkt_timer = QTimer(self)
        self._mkt_timer.timeout.connect(self._load_market_overview)
        self._mkt_timer.start(30000)


        # 内置定时学习（9/17/20点自动跑，后台线程，不占CPU）
        try:
            from auto_scheduler import AutoTrainScheduler
            self._scheduler = AutoTrainScheduler(self)
            self._scheduler.status_changed.connect(
                lambda msg: self.statusBar().showMessage(f'[自动学习] {msg}', 5000)
            )
        except Exception:
            pass
    def _show_announcement(self) -> None:
        from PyQt6.QtCore import QSettings
        settings = QSettings("Shuying", "ShuyingInsight")
        if settings.value("disclaimer_accepted", False, type=bool):
            return  # 已确认过，不再弹窗
        box = QMessageBox(self)
        box.setWindowTitle("免责声明与合规定位")
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText(
            "【免责声明】\n\n"
            "本工具为开源金融数据分析软件，仅供研究学习使用。\n\n"
            "不提供任何证券投资分析、预测或建议，不构成投资建议，不是荐股软件。\n\n"
            "开发者不具备证券投资咨询业务资格。\n\n"
            "投资有风险，入市需谨慎。\n\n"
            "点击确定进入程序。")
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        box.setDefaultButton(QMessageBox.StandardButton.Ok)
        box.exec()
        settings.setValue("disclaimer_accepted", True)
    def _ensure_on_screen(self) -> None:
        """确保窗口在可用屏幕区域内。"""
        from PyQt6.QtGui import QGuiApplication
        screen = QGuiApplication.screenAt(self.geometry().center())
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        avail = screen.availableGeometry()
        g = self.geometry()
        if g.right() > avail.right() or g.bottom() > avail.bottom() or g.left() < avail.left() or g.top() < avail.top():
            self.setGeometry(
                avail.x() + 50, avail.y() + 50,
                min(1200, avail.width() - 100),
                min(800, avail.height() - 100),
            )

    def closeEvent(self, event) -> None:
        from PyQt6.QtCore import QSettings
        settings = QSettings("Shuying", "ShuyingInsight")
        settings.setValue("geometry", self.saveGeometry())
        super().closeEvent(event)

    def _load_demo(self) -> None:
        """首次启动自动加载贵州茅台作为示例。"""
        try:
            self.chat_tab.input.setText("AAPL")
            self.chat_tab._analyze()
        except Exception:
            pass

    def _build_left_panel(self) -> QWidget:
        w = QWidget()
        w.setMaximumWidth(240)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 12, 8, 8)
        lay.setSpacing(4)

        # Logo
        logo = QLabel("🌙 疏影·知微")
        logo.setStyleSheet(f"font-size:16px; font-weight:bold; color:{ACCENT}; padding:8px;")
        lay.addWidget(logo)

        # 导航项（图标+名称→中央tab索引）
        nav_items = [
            ("💬 对话分析", 0), ("📊 市场概览", 1), ("⭐ 自选股", 2),
            ("📈 分析", 3), ("📉 K线图", 4), ("💼 模拟盘", 5),
            ("🔬 回测", 6), ("📊 组合回测", 7), ("⚙️ 参数寻优", 8),
            ("⏪ 信号回放", 9), ("📚 学习库", 10), ("📝 决策记录", 11),
            ("📋 分析日志", 12), ("🛡️ 合规审计", 13),
            ("🕸️ 产业图谱", 14), ("⚔️ 多空辩论", 15), ("📋 股票大全", 16),
        ]
        self.nav_buttons = []
        for label, idx in nav_items:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setStyleSheet(f"""
                QPushButton {{
                    text-align:left; padding:8px 12px; border:none;
                    border-radius:8px; color:{TEXT_SUB};
                }}
                QPushButton:hover {{ background:{BG_HOVER}; color:{TEXT_MAIN}; }}
                QPushButton:checked {{
                    background:rgba(0,229,255,0.12);
                    color:{ACCENT}; border-left:3px solid {ACCENT};
                }}
            """)
            btn.clicked.connect(lambda _, i=idx, b=btn: self._switch_tab(i, b))
            self.nav_buttons.append(btn)
            lay.addWidget(btn)


        # 券商官方开户入口
        from broker_links import list_brokers
        broker_card = QFrame()
        broker_card.setStyleSheet(f'background:{BG_CARD}; border:1px solid {BORDER}; border-radius:8px; padding:8px;')
        bl = QVBoxLayout(broker_card)
        bl.setContentsMargins(8, 8, 8, 8)
        title = QLabel('券商官方开户入口')
        title.setStyleSheet(f'color:{TEXT_MAIN}; font-weight:bold; font-size:12px;')
        bl.addWidget(title)
        self.broker_combo = QComboBox()
        self.broker_combo.addItems(list_brokers())
        bl.addWidget(self.broker_combo)
        open_btn = QPushButton('前往官方开户页面')
        open_btn.setStyleSheet(f'background:{ACCENT}; color:{BG_CARD}; border-radius:5px; padding:6px;')
        open_btn.clicked.connect(self._open_broker)
        bl.addWidget(open_btn)
        compliance = QLabel('仅提供跳转链接，不参与开户流程，不收集信息，不涉及佣金分成。')
        compliance.setWordWrap(True)
        compliance.setStyleSheet(f'color:{TEXT_SUB}; font-size:10px;')
        bl.addWidget(compliance)
        lay.addWidget(broker_card)
        lay.addStretch(1)
        return w

    def _on_tab_changed(self, idx: int) -> None:
        """懒加载：切换到对应tab时才创建。"""
        if idx in self._lazy_tabs and idx not in self._created:
            name, cls = self._lazy_tabs[idx]
            try:
                tab = cls()
                self.tabs.removeTab(idx)
                self.tabs.insertTab(idx, tab, name)
                self._created[idx] = tab
            except Exception:
                pass

    def _switch_tab(self, idx: int, btn: QPushButton) -> None:
        self.tabs.setCurrentIndex(idx)
        for b in self.nav_buttons:
            b.setChecked(False)
        btn.setChecked(True)

    # ---------- 三栏：右侧信息面板 ----------
    def _load_market_overview(self) -> None:
        """用yfinance异步加载市场概览数据。"""
        self.r_market.setText("📊 今日市场概览\n\n加载中...")
        class _MktWorker(QThread):
            done = pyqtSignal(str)
            fail = pyqtSignal(str)

            def run(self):
                lines = ["📊 今日市场概览", ""]
                # 先用yfinance获取
                try:
                    import yfinance as yf
                    indices = [
                        ("上证指数", "000001.SS"),
                        ("深证成指", "399001.SZ"),
                        ("创业板指", "399006.SZ"),
                        ("沪深300", "000300.SS"),
                    ]
                    for name, sym in indices:
                        try:
                            t = yf.Ticker(sym)
                            h = t.history(period="5d")
                            if len(h) >= 2:
                                last = h["Close"].iloc[-1]
                                prev = h["Close"].iloc[-2]
                                chg = (last - prev) / prev * 100
                                lines.append(f"{name}: {last:.2f} ({chg:+.2f}%)")
                            else:
                                lines.append(f"{name}: —")
                        except Exception:
                            lines.append(f"{name}: —")
                except Exception:
                    lines.append("（数据加载失败）")
                self.done.emit("\n".join(lines))

        self._mkt_w = _MktWorker()
        from core.config import now_cn
        self._mkt_w.done.connect(lambda text: self.r_market.setText(text + f"\n\n⏱ {now_cn().strftime('%H:%M:%S')}"))
        self._mkt_w.fail.connect(lambda e: self.r_market.setText(f"📊 今日市场概览\n\n（加载失败）"))
        self._mkt_w.start()

    def _build_right_panel(self) -> QWidget:
        w = QWidget()
        w.setMaximumWidth(320)
        w.setMinimumWidth(260)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 12, 8, 8)
        lay.setSpacing(8)

        # 个股信息卡片
        card1 = QFrame()
        card1.setStyleSheet(f"QFrame {{background:{BG_CARD}; border:1px solid {BORDER}; border-radius:12px;}}")
        c1l = QVBoxLayout(card1)
        c1l.setContentsMargins(12, 12, 12, 12)
        self.r_stock_name = QLabel("未选择股票")
        self.r_stock_name.setStyleSheet(f"font-size:16px; font-weight:bold; color:{TEXT_MAIN};")
        self.r_price = QLabel("—")
        self.r_price.setStyleSheet(f"font-size:22px; font-family:Consolas; color:{TEXT_MAIN};")
        self.r_change = QLabel("")
        self.r_change.setStyleSheet(f"font-size:13px; color:{TEXT_SUB};")
        c1l.addWidget(self.r_stock_name)
        c1l.addWidget(self.r_price)
        c1l.addWidget(self.r_change)

        # 默认市场概览（未选股时显示）
        self.r_market = QLabel("📊 今日市场概览\n\n上证指数: —\n深证成指: —\n创业板指: —\n北向资金: —\n两市成交: —")
        self.r_market.setStyleSheet(f"color:{TEXT_SUB}; font-size:12px;")
        c1l.addWidget(self.r_market)
        lay.addWidget(card1)

        # AI摘要卡片
        card2 = QFrame()
        card2.setStyleSheet(f"QFrame {{background:{BG_CARD}; border:1px solid {BORDER}; border-radius:12px;}}")
        c2l = QVBoxLayout(card2)
        c2l.setContentsMargins(12, 12, 12, 12)
        c2l.addWidget(QLabel("🤖 AI 摘要"))
        self.r_ai_summary = QLabel("分析后显示...")
        self.r_ai_summary.setWordWrap(True)
        self.r_ai_summary.setStyleSheet(f"color:{TEXT_SUB}; font-size:12px;")
        c2l.addWidget(self.r_ai_summary)
        lay.addWidget(card2)

        # 风险提示
        warn = QLabel("⚠️ 本分析仅为数据展示，不构成投资建议")
        warn.setWordWrap(True)
        warn.setStyleSheet(f"color:{WARN}; font-size:11px; padding:8px;")
        lay.addWidget(warn)

        lay.addStretch(1)
        return w


    def _open_broker(self):
        from broker_links import get_broker_link
        from safe_url_opener import safe_open_url
        name = self.broker_combo.currentText()
        info = get_broker_link(name)
        if not info:
            return
        reply = QMessageBox.question(
            self, '跳转确认',
            f'即将跳转至 {name} 官方页面。本程序不参与开户流程，不收集您的信息。是否继续？',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            safe_open_url(info['url'])
    def _on_chat_analysis(self, ticker: str, snap: dict) -> None:
        """chat_tab分析完成后更新右侧面板。"""
        price = snap.get("close")
        chg = snap.get("chg_pct_1d")
        if price:
            self.r_stock_name.setText(f"{ticker}")
            self.r_price.setText(f"{price:.2f}")
            if chg is not None:
                color = "#00C853" if chg >= 0 else "#FF1744"
                self.r_change.setText(f"<span style='color:{color}'>{chg:+.2f}%</span>")
                self.r_change.setStyleSheet(f"font-size:13px;")
            rsi = snap.get("rsi14")
            macd = snap.get("macd_signal", "")
            self.r_ai_summary.setText(f"RSI(14): {rsi:.1f}\nMACD: {macd}\n数据已加载")

    def _on_analysis_done(self, result: dict) -> None:
        self.history_tab.refresh()
        self.paper_tab.refresh()
        self._log_analysis(result)
        state = result.get("state") or {}
        ticker = state.get("ticker")
        if ticker:
            self.chart_tab.load(ticker)
            # 刷新右侧面板
            name = state.get("name", ticker)
            summary = (state.get("final") or {}).get("summary", "")
            self.r_stock_name.setText(f"{name}  {ticker}")
            self.r_ai_summary.setText(summary[:200] + ("..." if len(summary) > 200 else ""))

    def _log_analysis(self, result: dict) -> None:
        """把本次 AI 分析落库到 decision_logger（任何失败不影响主流程）。"""
        try:
            from decision_logger import log_decision
            from schemas import parse_structured
            state = result.get("state") or {}
            ticker = state.get("ticker", "")
            if not ticker:
                return
            final = state.get("final") or {}
            tokens = state.get("tokens") or {}
            # 完整报告文本作为 raw_output
            try:
                from core.report import render as render_report
                raw_text = render_report(state)
            except Exception:  # noqa: BLE001
                raw_text = final.get("summary", "")
            # 结构化输出尝试解析
            payload = {
                "indicators": state.get("tech") or {},
                "summary": final.get("summary", ""),
                "data_sources": state.get("sources") or [],
                "confidence": final.get("confidence") or 50,
            }
            structured, _ok = parse_structured("technical", raw_text, payload)
            log_decision(
                stock_code=ticker,
                stock_name=state.get("name", "") or ticker,
                model_used=tokens.get("model", ""),
                analysis_type="综合分析",
                raw_output=raw_text,
                structured_output=structured,
                confidence_score=final.get("confidence"),
                data_sources=state.get("sources") or [],
            )
            if hasattr(self, "analysis_log_tab"):
                self.analysis_log_tab.refresh()
        except Exception:  # noqa: BLE001 - 日志失败静默
            pass

    def _on_watchlist_analyze(self, ticker: str) -> None:
        self.analysis_tab.input.setText(ticker)
        self.tabs.setCurrentWidget(self.analysis_tab)

    def _on_watchlist_triggered(self, ticker: str, msg: str) -> None:
        if self.tray is not None:
            self.tray.showMessage(
                ticker, msg + "\n（仅供参考）",
                QSystemTrayIcon.MessageIcon.Warning, 10000)
        self.activateWindow()
        self.raise_()

    # ---------- 开发者调试面板（仅 dev 模式） ----------
    def _build_debug_panel(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(QLabel("开发者调试工具（仅本机使用，不影响普通用户）"))

        b_clear = QPushButton("清空本地缓存")
        b_clear.clicked.connect(self._debug_clear_cache)
        lay.addWidget(b_clear)

        b_log = QPushButton("查看系统日志")
        b_log.clicked.connect(self._debug_show_log)
        lay.addWidget(b_log)

        lay.addStretch(1)
        return w

    def _debug_clear_cache(self) -> None:
        try:
            from core.data import cache
            cache.clear_all()
            QMessageBox.information(self, "开发者", "本地缓存已清空。")
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "开发者", f"清空失败：{e}")

    def _debug_show_log(self) -> None:
        dlg = QMessageBox(self)
        dlg.setWindowTitle("系统日志（data/ 目录）")
        logs = [p.name for p in DATA_DIR.glob("*.log")]
        dlg.setText("本地日志文件：\n" + ("\n".join(logs) or "（暂无）"))
        dlg.exec()

    # ---------- 应用内反馈（跳转 GitHub Issues，不上传数据） ----------
    def _open_feedback(self) -> None:
        from PyQt6.QtWidgets import QDialog, QComboBox
        from urllib.parse import quote
        import webbrowser

        REPO = "https://github.com/ShuYing07/Penumbra"
        dlg = QDialog(self)
        dlg.setWindowTitle("意见反馈")
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel("反馈类型："))
        kind = QComboBox()
        kind.addItems(["Bug", "建议", "其他"])
        lay.addWidget(kind)
        lay.addWidget(QLabel("描述："))
        box = QTextEdit()
        box.setPlaceholderText("请描述你遇到的问题或建议（不会上传到本程序，仅在你提交时跳转 GitHub）")
        lay.addWidget(box)
        btn = QPushButton("提交（打开 GitHub Issue）")
        lay.addWidget(btn)

        def submit() -> None:
            text = box.toPlainText().strip() or "（无描述）"
            tag = kind.currentText()
            url = (f"{REPO}/issues/new?title="
                   f"{quote(f'[{tag}] 用户反馈')}&body={quote(text)}")
            webbrowser.open(url)
            dlg.accept()

        btn.clicked.connect(submit)
        dlg.exec()

    def _open_api_settings(self) -> None:
        from app.ui.api_settings_dialog import APISettingsDialog
        dlg = APISettingsDialog(self)
        dlg.exec()

    def _check_update(self) -> None:
        import webbrowser
        from config_manager import check_update, APP_VERSION, RELEASES_URL
        res = check_update()
        url = res.get("url") or RELEASES_URL
        box = QMessageBox(self)
        box.setWindowTitle("检查更新")
        if res.get("has_update"):
            box.setIcon(QMessageBox.Icon.Information)
            box.setText(
                f"发现新版本：v{res['latest']}（当前 v{APP_VERSION}）。\n"
                f"程序不会自动更新，请前往 GitHub Releases 查看与下载。")
        else:
            box.setIcon(QMessageBox.Icon.Information)
            box.setText(
                f"当前版本 v{APP_VERSION}。\n"
                f"我们不架设自己的更新服务器，所有版本与更新说明都发布在\n"
                f"GitHub Releases 页面，点下方按钮即可查看。")
        btn_web = box.addButton("前往 GitHub Releases", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("关闭", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is btn_web:
            webbrowser.open(url)

    def _open_sponsor(self) -> None:
        import webbrowser
        from PyQt6.QtWidgets import QDialog, QInputDialog

        AFD = "https://afdian.com/shuying07"

        dlg = QDialog(self)
        dlg.setWindowTitle("支持开发者")
        dlg.setStyleSheet("background:#0D1117; color:#E6EDF3;")
        lay = QVBoxLayout(dlg)

        lay.addWidget(QLabel(
            "如果这个工具对你有帮助，欢迎支持我持续开发。\n"
            "你的支持将用于支付 API 费用和服务器成本。"))

        chosen = {"amount": 10}

        def pick(amt):
            chosen["amount"] = amt

        row_btns = QHBoxLayout()
        for amt in (10, 50, 200):
            b = QPushButton(f"¥{amt}")
            b.setStyleSheet(
                "background-color:#2F81F7; color:white; border-radius:5px; padding:5px;")
            b.clicked.connect(lambda _, a=amt: pick(a))
            row_btns.addWidget(b)
        b_custom = QPushButton("自定义")
        b_custom.setStyleSheet(
            "background-color:#2F81F7; color:white; border-radius:5px; padding:5px;")

        def custom():
            v, ok = QInputDialog.getInt(dlg, "自定义金额", "金额（元）：", 10, 1, 10000)
            if ok:
                pick(v)
        b_custom.clicked.connect(custom)
        row_btns.addWidget(b_custom)
        lay.addLayout(row_btns)

        go = QPushButton("前往支持")
        go.setStyleSheet(
            "background-color:#2F81F7; color:white; border-radius:5px; padding:6px;")

        def submit():
            webbrowser.open(f"{AFD}?amount={chosen['amount']}")
            dlg.accept()
        go.clicked.connect(submit)
        lay.addWidget(go)

        lay.addWidget(QLabel("您的支持是我持续更新的动力 🙏"))
        dlg.exec()
