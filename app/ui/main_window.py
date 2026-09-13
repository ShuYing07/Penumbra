# -*- coding: utf-8 -*-
"""主窗口：自选股/分析/K线图/模拟盘/回测/参数寻优/信号回放/学习库/决策记录 九标签 + 托盘。"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (QLabel, QMainWindow, QStatusBar, QStyle, QSystemTrayIcon,
                             QTabWidget, QWidget, QVBoxLayout, QPushButton, QMessageBox,
                             QTextEdit)

from app.ui.analysis_tab import AnalysisTab
from app.ui.backtest_tab import BacktestTab
from app.ui.chat_tab import ChatTab
from app.ui.chart_tab import ChartTab
from app.ui.history_tab import HistoryTab
from app.ui.knowledge_tab import KnowledgeTab
from app.ui.optimize_tab import OptimizeTab
from app.ui.overview_tab import OverviewTab
from app.ui.paper_tab import PaperTab
from app.ui.portfolio_tab import PortfolioTab
from app.ui.replay_tab import ReplayTab
from app.ui.watchlist_tab import WatchlistTab
from config_manager import is_dev_mode
from core.config import DISCLAIMER, DATA_DIR


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("StockAIPredictor · 虚拟股票预测（学习研究版）")
        self.resize(1200, 800)

        self.watchlist_tab = WatchlistTab()
        self.chat_tab = ChatTab()
        self.overview_tab = OverviewTab()
        self.analysis_tab = AnalysisTab()
        self.chart_tab = ChartTab()
        self.paper_tab = PaperTab()
        self.backtest_tab = BacktestTab()
        self.optimize_tab = OptimizeTab()
        self.portfolio_tab = PortfolioTab()
        self.replay_tab = ReplayTab()
        self.knowledge_tab = KnowledgeTab()
        self.history_tab = HistoryTab()

        self.tabs = QTabWidget()
        self.tabs.addTab(self.chat_tab, "对话分析")
        self.tabs.addTab(self.overview_tab, "市场概览")
        self.tabs.addTab(self.watchlist_tab, "自选股")
        self.tabs.addTab(self.analysis_tab, "分析")
        self.tabs.addTab(self.chart_tab, "K线图")
        self.tabs.addTab(self.paper_tab, "模拟盘")
        self.tabs.addTab(self.backtest_tab, "回测")
        self.tabs.addTab(self.portfolio_tab, "组合回测")
        self.tabs.addTab(self.optimize_tab, "参数寻优")
        self.tabs.addTab(self.replay_tab, "信号回放")
        self.tabs.addTab(self.knowledge_tab, "学习库")
        self.tabs.addTab(self.history_tab, "决策记录")
        self.setCentralWidget(self.tabs)

        # 开发者调试面板：仅 DEV_MODE=true 时显示，否则完全隐藏
        if is_dev_mode():
            self.tabs.addTab(self._build_debug_panel(), "开发者工具")

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
            self.tray.setToolTip("StockAIPredictor 盯盘")
            self.tray.messageClicked.connect(self.showNormal)
            self.tray.show()

        # 联动：分析完成 → 刷新决策记录 / K线图自动载入 / 模拟盘刷新
        self.analysis_tab.analysis_finished.connect(self._on_analysis_done)
        # 自选股 → 加入分析（双击/右键）
        self.watchlist_tab.analyze_requested.connect(self._on_watchlist_analyze)
        # 自选股触发 → 托盘气泡通知
        self.watchlist_tab.triggered.connect(self._on_watchlist_triggered)

        # 帮助菜单：意见反馈（不收集数据，跳转 GitHub Issues）
        bar = self.menuBar()
        help_menu = bar.addMenu("帮助")
        help_menu.addAction("意见反馈", self._open_feedback)
        help_menu.addAction("检查更新", self._check_update)
        help_menu.addAction("❤️ 支持开发者", self._open_sponsor)

    def _on_analysis_done(self, result: dict) -> None:
        self.history_tab.refresh()
        self.paper_tab.refresh()
        ticker = (result.get("state") or {}).get("ticker")
        if ticker:
            self.chart_tab.load(ticker)

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

        REPO = "https://github.com/ShuYing07/StockAIPredictor"
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

    def _check_update(self) -> None:
        from config_manager import check_update, APP_VERSION
        res = check_update()
        if res.get("error"):
            QMessageBox.information(self, "检查更新",
                                    f"无法连接更新服务器（{res['error']}）。\n当前版本 {APP_VERSION}。")
            return
        if res["has_update"]:
            QMessageBox.information(
                self, "检查更新",
                f"发现新版本：v{res['latest']}（当前 v{APP_VERSION}）。\n"
                f"请自行前往 GitHub Release 查看并下载，程序不会自动更新。\n{res['url'] or ''}")
        else:
            QMessageBox.information(self, "检查更新",
                                    f"已是最新版本 v{APP_VERSION}。")

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
        for amt in (5, 10, 20, 50):
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


