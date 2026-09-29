# -*- coding: utf-8 -*-
"""主窗口：Widget 化工作区（左侧导航 + 中央工作区 + 可停靠信息面板）。"""
from __future__ import annotations

import logging

from PyQt6.QtCore import Qt, QTimer, QSize, QThread, pyqtSignal
from PyQt6.QtGui import QIcon, QAction, QKeySequence, QShortcut
from PyQt6.QtWidgets import (QLabel, QMainWindow, QStatusBar, QStyle, QSystemTrayIcon,
                             QTabWidget, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                             QMessageBox, QTextEdit, QComboBox, QSplitter, QListWidget,
                             QListWidgetItem, QStackedWidget, QFrame, QSizePolicy,
                             QDockWidget)

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
from app.ui.collaboration_tab import CollaborationTab
from app.ui.risk_tab import RiskTab
from app.ui.data_source_tab import DataSourceTab
from app.ui.privacy_tab import PrivacyTab
from app.ui.valuation_tab import ValuationTab
from app.ui.compliance_monitor_tab import ComplianceMonitorTab
from app.ui.ui_theme import (BG_CARD, BORDER, TEXT_MAIN, TEXT_SUB, ACCENT,
                            UP, DOWN, WARN, BG_HOVER,
                            current_theme, set_theme, apply_theme, toggle_theme)
from config_manager import is_dev_mode
from core.config import DISCLAIMER, DATA_DIR
from i18n import tr

log = logging.getLogger("stockai.ui.main_window")

# 导航分组（模块一：按任务阶段分组 —— 发现 / 研究 / 验证 / 积累 / 系统）
NAV_GROUPS: list[tuple[str, list[tuple[str, int]]]] = [
    ("发现", [("💬 对话分析", 0), ("📊 市场概览", 1), ("📋 股票大全", 16)]),
    ("研究", [("⭐ 自选股", 2), ("📈 分析", 3), ("📉 K线图", 4),
              ("⚔️ 多空辩论", 15), ("🕸️ 产业图谱", 14)]),
    ("验证", [("💼 模拟盘", 5), ("🔬 回测", 6), ("📊 组合回测", 7),
              ("⚙️ 参数寻优", 8), ("⏪ 信号回放", 9)]),
    ("积累", [("📚 学习库", 10), ("📝 决策记录", 11), ("📋 分析日志", 12),
              ("🛡️ 合规审计", 13), ("⚖️ Swarm估值", 21), ("🛡️ 合规监控", 22)]),
    ("系统", [("🤝 协作空间", 17), ("🛡️ 风控", 18),
              ("🔌 数据源", 19), ("🔒 隐私与数据", 20)]),
]
NAV_ITEMS: list[tuple[str, int]] = [item for _g, items in NAV_GROUPS for item in items]


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(tr("app.title"))
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
        self.chat_tab.request_tab.connect(
            lambda idx: self._switch_tab(idx, self._nav_btn_of(idx)))
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
            17: ("协作空间", CollaborationTab),
            18: ("风控", RiskTab),
            19: ("数据源", DataSourceTab),
            20: ("隐私与数据", PrivacyTab),
            21: ("Swarm估值", ValuationTab),
            22: ("合规监控", ComplianceMonitorTab),
        }
        self._created = {}

        # 中央标签页
        self.tabs = QTabWidget()
        self.tabs.addTab(self.chat_tab, "对话分析")
        self.tabs.addTab(self.overview_tab, "市场概览")
        self.tabs.addTab(self.watchlist_tab, "自选股")
        self.tabs.addTab(self.analysis_tab, "分析")
        self.tabs.addTab(self.chart_tab, "K线图")
        for i in range(5, 23):
            name, _ = self._lazy_tabs[i]
            self.tabs.addTab(QWidget(), name)
        self.tabs.currentChanged.connect(self._on_tab_changed)

        # 确保数据库表初始化
        try:
            from core.memory.decision_log import init as _dl_init
            _dl_init()
        except Exception:
            pass

        # 企业深化运行时激活（Agent Mesh 注册 + 哈希链审计，失败不影响启动）
        try:
            from agent_mesh.agent_registry import register_agent as _reg_agent
            _reg_agent("main-analyst", "1.0", ["analysis", "chat"])
            _reg_agent("risk-guard", "1.0", ["compliance", "gate"])
            from security.audit_ledger import append as _aud
            _aud("system", "app_start", "ShuyingInsight 启动")
        except Exception:
            pass

        # 隐藏顶部tab栏，只通过左侧导航切换
        self.tabs.tabBar().hide()

        # 开发者调试面板
        if is_dev_mode():
            self.tabs.addTab(self._build_debug_panel(), "开发者工具")

        # Widget 化工作区（模块一）：中央 Tabs 为主画布，
        # 左侧导航 + 右侧信息面板为 QDockWidget（布局可保存/恢复）。
        self.setCentralWidget(self.tabs)

        # 左：导航停靠面板（固定，防误关）
        left_panel = self._build_left_panel()
        self.nav_dock = QDockWidget(tr("dock.nav"), self)
        self.nav_dock.setObjectName("navDock")
        self.nav_dock.setFeatures(
            QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)
        self.nav_dock.setWidget(left_panel)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.nav_dock)

        # 右：信息面板（可浮动/关闭，可从菜单恢复）
        right_panel = self._build_right_panel()
        self.info_dock = QDockWidget(tr("dock.info"), self)
        self.info_dock.setObjectName("infoDock")
        self.info_dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable)
        self.info_dock.setWidget(right_panel)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.info_dock)
        self.info_dock.resize(300, 700)

        # 恢复上次停靠布局（须在 dock 构建之后立即调用）
        try:
            _st = QSettings("Shuying", "ShuyingInsight").value("dock_state")
            if _st:
                self.restoreState(_st)
        except Exception:  # noqa: BLE001
            pass

        sb = QStatusBar()
        sb.addWidget(QLabel("⚠️ 本工具仅供研究学习，不构成投资建议"))
        sb.addPermanentWidget(QLabel("    "))
        # 主题切换（模块二：明暗一键切换，快捷键 Ctrl+M）
        self.theme_btn = QPushButton("🌙 暗色" if current_theme() == "dark" else "☀️ 浅色")
        self.theme_btn.setToolTip("切换明暗主题（Ctrl+M）")
        self.theme_btn.setStyleSheet(
            "background-color:#21262D; color:#8B949E; border-radius:5px; padding:4px 10px;"
        )
        self.theme_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.theme_btn.clicked.connect(self._toggle_theme)
        sb.addPermanentWidget(self.theme_btn)
        # 语言切换（中/EN）：轻量 i18n，部分界面文本重启后完全生效
        lang_btn = QPushButton(tr("lang.btn"))
        lang_btn.setToolTip(tr("lang.tip"))
        lang_btn.setStyleSheet(
            "background-color:#21262D; color:#8B949E; border-radius:5px; padding:4px 10px;"
        )
        lang_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        lang_btn.clicked.connect(self._toggle_language)
        sb.addPermanentWidget(lang_btn)
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
        view_menu = bar.addMenu("视图")
        view_menu.addAction("显示/隐藏信息面板", self._toggle_info_dock)
        view_menu.addAction("恢复默认布局", self._reset_dock_layout)
        help_menu = bar.addMenu("帮助")
        help_menu.addAction("意见反馈", self._open_feedback)
        help_menu.addAction("API 设置", self._open_api_settings)
        help_menu.addAction("检查更新", self._check_update)
        help_menu.addAction("❤️ 支持开发者", self._open_sponsor)

        # 模块三：全局快捷键（Ctrl+K 命令面板 / Ctrl+1~9 导航 / Ctrl+M 主题 / Ctrl+Shift+*）
        QShortcut(QKeySequence("Ctrl+K"), self, activated=self._open_command_palette)
        for i in range(1, 10):
            if i - 1 < len(self.nav_buttons):
                QShortcut(QKeySequence(f"Ctrl+{i}"), self,
                          activated=lambda _i=i - 1: self._switch_tab(
                              NAV_ITEMS[_i][1], self.nav_buttons[_i]))
        QShortcut(QKeySequence("Ctrl+M"), self, activated=self._toggle_theme)
        QShortcut(QKeySequence("Ctrl+Shift+A"), self,
                  activated=lambda: self._switch_tab(0, self.nav_buttons[0]))
        QShortcut(QKeySequence("Ctrl+Shift+B"), self,
                  activated=lambda: self._switch_tab(15, self._nav_btn_of(15)))
        QShortcut(QKeySequence("Ctrl+Shift+R"), self,
                  activated=lambda: self._switch_tab(6, self._nav_btn_of(6)))

        # 模块三：浮动 AI 按钮（右下角）
        self.ai_fab = QPushButton("🤖", self)
        self.ai_fab.setToolTip("AI 助手：快速唤起对话分析（感知当前股票）")
        self.ai_fab.setFixedSize(52, 52)
        self.ai_fab.setCursor(Qt.CursorShape.PointingHandCursor)
        self.ai_fab.setStyleSheet(
            "QPushButton{background:rgba(0,229,255,0.18); border:1px solid #00E5FF;"
            "border-radius:26px; font-size:22px; color:#00E5FF;}"
            "QPushButton:hover{background:rgba(0,229,255,0.32);}")
        self.ai_fab.clicked.connect(self._open_ai_assistant)
        self.ai_fab.raise_()

        # 启动公告：延迟弹出，提示用户去 GitHub 查看最新版本
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(600, self._show_announcement)
        QTimer.singleShot(1500, self._load_market_overview)
        # 首次启动自动加载示例股票（贵州茅台 600519）
        QTimer.singleShot(2000, self._load_demo)
        # 模块六：首次启动欢迎引导（3 页，可跳过）
        QTimer.singleShot(1200, self._maybe_show_onboarding)
        # 启动网络探测：失败→状态栏红字提示+重试按钮+自动降级缓存/示例（模块二）
        QTimer.singleShot(2500, self._startup_network_probe)
        # 知识库首灌改为懒触发（打开「学习库」tab 且库为空时后台入库），
        # 避免与市场概览/网络探测在启动期并发（多线程竞态偶发崩溃）。
        # 每30秒刷新市场概览
        self._mkt_timer = QTimer(self)
        self._mkt_timer.timeout.connect(self._load_market_overview)
        self._mkt_timer.start(30000)

        # 模块七：每日自动简报（07:30 检查，仅当天首次生成一次）
        self._brief_timer = QTimer(self)
        self._brief_timer.timeout.connect(self._maybe_daily_briefing)
        self._brief_timer.start(60000)  # 每分钟检查一次


        # 内置定时学习（9/17/20点自动跑，后台线程，不占CPU）
        try:
            from auto_scheduler import AutoTrainScheduler
            self._scheduler = AutoTrainScheduler(self)
            self._scheduler.status_changed.connect(
                lambda msg: self.statusBar().showMessage(f'[自动学习] {msg}', 5000)
            )
        except Exception:
            pass
    def _prime_knowledge_base(self) -> None:
        """学习库懒灌：仅当向量库为空时后台入库（打开「学习库」tab 触发）。"""
        try:
            from memory.vector_memory import stats as _vstats
            if _vstats()["docs"] > 0:
                return
        except Exception:  # noqa: BLE001
            pass
        import threading
        def _work():
            try:
                from core.memory import rag
                n = rag.index_reports(50) + rag.index_news(None, 300) + rag.index_reflections(200)
                def _msg():
                    self.statusBar().showMessage(
                        f"[学习库] 已自动入库 {n} 条本地资料" if n >= 0
                        else "[学习库] 入库失败（不影响使用）", 6000)
                QTimer.singleShot(0, _msg)
            except Exception:  # noqa: BLE001
                pass
        threading.Thread(target=_work, daemon=True).start()

    def _show_announcement(self) -> None:
        from PyQt6.QtCore import QSettings
        settings = QSettings("Shuying", "ShuyingInsight")
        if settings.value("disclaimer_accepted", False, type=bool):
            return  # 已确认过，不再弹窗
        box = QMessageBox(self)
        box.setWindowTitle(tr("disclaimer.title"))
        box.setIcon(QMessageBox.Icon.Information)
        box.setText(tr("disclaimer.body"))
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        box.setDefaultButton(QMessageBox.StandardButton.Ok)
        box.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        box.setWindowModality(Qt.WindowModality.NonModal)  # 非模态，不阻塞程序
        box.show()
        settings.setValue("disclaimer_accepted", True)
    def _toggle_language(self) -> None:
        """切换界面语言（zh ⇄ en）并即时更新关键可见文本。"""
        from i18n import set_language, current_lang, tr as _tr, LANGUAGES
        nxt = "en" if current_lang() == "zh" else "zh"
        set_language(nxt)
        self.setWindowTitle(_tr("app.title"))
        if hasattr(self, "web_btn"):
            self.web_btn.setText(_tr("web.btn"))
        self.statusBar().showMessage(
            _tr("status.lang_switched") + f"（{LANGUAGES[nxt]}）", 6000)

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
        # 模块一：保存停靠布局（Widget 工作区）
        try:
            settings.setValue("dock_state", self.saveState())
        except Exception:  # noqa: BLE001
            pass
        super().closeEvent(event)

    # ---------- 模块二：主题切换 ----------
    def _toggle_theme(self) -> None:
        name = toggle_theme()
        from PyQt6.QtWidgets import QApplication
        apply_theme(QApplication.instance())
        self.theme_btn.setText("🌙 暗色" if name == "dark" else "☀️ 浅色")
        self.statusBar().showMessage(f"已切换到{'暗色 · 玻璃态' if name == 'dark' else '浅色 · 舒适'}主题", 3000)

    # ---------- 模块一：信息面板显隐与布局重置 ----------
    def _toggle_info_dock(self) -> None:
        self.info_dock.setVisible(not self.info_dock.isVisible())

    def _reset_dock_layout(self) -> None:
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.nav_dock)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.info_dock)
        self.statusBar().showMessage("已恢复默认布局", 3000)

    def _nav_btn_of(self, idx: int) -> QPushButton:
        for i, (_, _idx) in enumerate(NAV_ITEMS):
            if _idx == idx and i < len(self.nav_buttons):
                return self.nav_buttons[i]
        return self.nav_buttons[0]

    # ---------- 模块三：全局命令面板 / 浮动 AI ----------
    def _open_command_palette(self) -> None:
        from app.ui.command_palette import CommandPaletteDialog
        dlg = CommandPaletteDialog(NAV_ITEMS, self)
        dlg.execute.connect(self._on_command_execute)
        dlg.exec()

    def _on_command_execute(self, kind: int, payload) -> None:
        try:
            if kind == 0:  # 功能导航
                self._switch_tab(int(payload), self._nav_btn_of(int(payload)))
            elif kind == 1:  # 股票
                code = payload.get("code", "")
                if code:
                    self._open_stock(code)
            elif kind == 2:  # 历史
                code = payload.get("code", "")
                if code:
                    self._open_stock(code)
        except Exception as e:  # noqa: BLE001
            self.statusBar().showMessage(f"命令执行失败：{e}", 4000)

    def _open_stock(self, code: str) -> None:
        """从命令面板打开某只股票：切到分析页并填入代码，K线同步加载。"""
        self.analysis_tab.input.setText(code)
        self.tabs.setCurrentWidget(self.analysis_tab)
        try:
            self.chart_tab.load(code)
        except Exception:  # noqa: BLE001
            pass

    def _open_ai_assistant(self) -> None:
        """浮动 AI 按钮：唤起对话分析，自动感知当前选中的股票。"""
        cur = ""
        try:
            # 感知当前股票：优先分析页输入框，其次右侧面板标题
            t = self.analysis_tab.input.text().strip()
            if t:
                cur = t
            elif self.r_stock_name.text() and "未选择" not in self.r_stock_name.text():
                cur = self.r_stock_name.text().split()[-1]
        except Exception:  # noqa: BLE001
            pass
        self._switch_tab(0, self._nav_btn_of(0))
        if cur:
            self.chat_tab.input.setText(cur)
            self.chat_tab.input.setFocus()
        else:
            self.chat_tab.input.setFocus()

    def resizeEvent(self, e) -> None:  # noqa: N802
        super().resizeEvent(e)
        if hasattr(self, "ai_fab"):
            m = 24
            self.ai_fab.move(self.width() - self.ai_fab.width() - m,
                             self.height() - self.ai_fab.height() - m)
            self.ai_fab.raise_()

    # ---------- 模块六：首次启动引导 ----------
    def _maybe_show_onboarding(self) -> None:
        from PyQt6.QtCore import QSettings
        settings = QSettings("Shuying", "ShuyingInsight")
        if settings.value("onboarding_done", False, type=bool):
            return
        settings.setValue("onboarding_done", True)
        try:
            from app.ui.onboarding import OnboardingDialog
            dlg = OnboardingDialog(self)
            dlg.exec()
        except Exception:  # noqa: BLE001
            pass

    # ---------- 模块七：每日自动简报 ----------
    def _maybe_daily_briefing(self) -> None:
        from datetime import datetime, date
        now = datetime.now()
        if now.hour != 7 or now.minute != 30:
            return
        today = date.today().strftime("%Y-%m-%d")
        import os as _os
        from core.daily_briefing import briefing_path
        if _os.path.exists(briefing_path(today)):
            return  # 当天已生成
        try:
            from core.daily_briefing import build_briefing
            html = build_briefing(now)
            if self.tray is not None:
                self.tray.showMessage(
                    "📰 每日市场简报", html,
                    QSystemTrayIcon.MessageIcon.Information, 8000)
            self.statusBar().showMessage("📰 今日市场简报已生成", 5000)
        except Exception as e:  # noqa: BLE001
            log.debug("每日简报生成失败: %s", e)

    def _load_demo(self) -> None:
        """首次启动自动加载示例股票 AAPL（苹果）示例数据（只加载K线，不跑LLM，避免启动慢）。"""
        from PyQt6.QtCore import QSettings
        settings = QSettings("Shuying", "ShuyingInsight")
        first = not settings.value("demo_loaded", False, type=bool)
        if not first:
            return
        settings.setValue("demo_loaded", True)
        try:
            self.chat_tab.input.setText("AAPL")
            self.chart_tab.load("AAPL")
        except Exception:
            pass

    # ---------- 模块二：启动网络探测与降级 ----------
    def _startup_network_probe(self) -> None:
        """后台线程探测数据源；失败时状态栏红字+『重试』按钮，并按 缓存→示例 降级。"""
        if getattr(self, "_probe_w", None) and self._probe_w.isRunning():
            return
        from core.error_handler import check_network_and_fallback

        class _Probe(QThread):
            done = pyqtSignal(dict)

            def run(self):
                try:
                    self.done.emit(check_network_and_fallback("SH600519"))
                except Exception as e:  # noqa: BLE001
                    from core.error_handler import handle_network_error
                    self.done.emit(handle_network_error(e, "startup probe"))

        self._probe_w = _Probe()
        self._probe_w.done.connect(self._on_probe_done)
        self._probe_w.start()

    def _on_probe_done(self, result: dict) -> None:
        from core.error_handler import network_status_bar
        if result.get("ok"):
            # 清理旧状态栏降级提示（若有）
            sb = self.statusBar()
            for w in getattr(self, "_net_widgets", []):
                try:
                    sb.removeWidget(w)
                    w.deleteLater()
                except Exception:  # noqa: BLE001
                    pass
            self._net_widgets = []
            self.statusBar().showMessage(tr("status.datasource_ok"), 3000)
        else:
            network_status_bar(self, result, retry=self._startup_network_probe)

    def _build_left_panel(self) -> QWidget:
        w = QWidget()
        w.setMaximumWidth(240)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 12, 8, 8)
        lay.setSpacing(4)

        # Logo
        logo = QLabel(tr("app.logo"))
        logo.setStyleSheet(f"font-size:16px; font-weight:bold; color:{ACCENT}; padding:8px;")
        lay.addWidget(logo)

        # 导航项（模块一：按任务阶段分组 —— 发现/研究/验证/积累/系统）
        self.nav_buttons = []
        for group, items in NAV_GROUPS:
            gh = QLabel(group)
            gh.setStyleSheet(
                f"color:{TEXT_SUB}; font-size:11px; font-weight:bold;"
                f"padding:6px 10px 2px 10px;")
            lay.addWidget(gh)
            for label, idx in items:
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

        # Web 界面入口（企业版混合模式）
        self.web_btn = QPushButton(tr('web.btn'))
        self.web_btn.setToolTip('启动本地 FastAPI 服务并在浏览器打开（需已安装 fastapi/uvicorn）')
        self.web_btn.setStyleSheet(f'''
            QPushButton {{
                text-align:left; padding:8px 12px; border:1px dashed {BORDER};
                border-radius:8px; color:{TEXT_SUB};
            }}
            QPushButton:hover {{ border-color:{ACCENT}; color:{ACCENT}; }}
        ''')
        self.web_btn.clicked.connect(self._open_web_ui)
        lay.addWidget(self.web_btn)
        lay.addStretch(1)
        return w

    def _on_tab_changed(self, idx: int) -> None:
        """懒加载：切换到对应tab时才创建。"""
        if idx in self._lazy_tabs and idx not in self._created:
            name, cls = self._lazy_tabs[idx]
            try:
                tab = cls()
                cur = self.tabs.currentIndex()
                self.tabs.removeTab(idx)
                self.tabs.insertTab(idx, tab, name)
                self._created[idx] = tab
                # removeTab/insertTab 会扰动 currentIndex（移除当前页后 Qt
                # 自动激活相邻页），恢复到目标页，避免"点击 A 却显示 A 的前一页"
                if self.tabs.currentIndex() != cur:
                    self.tabs.setCurrentIndex(cur)
                _attr = {11: "history_tab", 5: "paper_tab", 12: "analysis_log_tab"}.get(idx)
                if _attr:
                    setattr(self, _attr, tab)
                if idx == 10:
                    # 打开「学习库」时懒灌知识库（库为空才入库，后台线程）
                    self._prime_knowledge_base()
            except Exception:
                pass

    def _switch_tab(self, idx: int, btn: QPushButton) -> None:
        self.tabs.setCurrentIndex(idx)
        for b in self.nav_buttons:
            b.setChecked(False)
        btn.setChecked(True)

    # ---------- 三栏：右侧信息面板 ----------
    def _load_market_overview(self) -> None:
        """用新浪实时行情异步加载市场概览数据。防并发：旧worker未结束则跳过。"""
        if getattr(self, "_mkt_w", None) and self._mkt_w.isRunning():
            return
        self.r_market.setText("📊 今日市场概览\n\n加载中...")
        class _MktWorker(QThread):
            done = pyqtSignal(str)
            fail = pyqtSignal(str)

            def run(self):
                try:
                    from core.data.market_overview import list_market_indices
                    items = list_market_indices()
                    if not items:
                        self.fail.emit("empty")
                        return
                    lines = ["📊 今日市场概览", ""]
                    for it in items:
                        lines.append(f"{it['name']}: {it['price']:.2f} ({it['chg_pct']:+.2f}%)")
                    self.done.emit("\n".join(lines))
                except Exception as e:  # noqa: BLE001
                    self.fail.emit(str(e))

        self._mkt_w = _MktWorker()
        from core.config import now_cn
        self._mkt_w.done.connect(lambda text: self.r_market.setText(text + f"\n\n⏱ {now_cn().strftime('%H:%M:%S')}"))
        self._mkt_w.fail.connect(self._on_market_overview_fail)
        self._mkt_w.start()

    def _on_market_overview_fail(self, _e: str) -> None:
        """市场概览失败：右侧面板占位 + 状态栏非阻塞提示（可重试），不弹阻塞式弹窗。"""
        self.r_market.setText("📊 今日市场概览\n\n（加载失败）")
        try:
            from core.error_handler import handle_network_error
            from core.data import cache
            if cache.load_bars("SH600519").empty:
                msg = "市场概览加载失败；无缓存，可稍后点击『重试』"
            else:
                msg = "市场概览加载失败，已切换到缓存数据"
        except Exception:  # noqa: BLE001
            msg = "市场概览加载失败，可点击『重试』"
        self.statusBar().showMessage(msg)
        # 每 30s 定时器会自动重试；此处同时提供手动重试入口（状态栏常驻按钮）
        try:
            from core.error_handler import network_status_bar
            network_status_bar(self, {"ok": False, "source": "none", "message": msg},
                               retry=self._load_market_overview)
        except Exception:  # noqa: BLE001
            pass

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


    def _open_web_ui(self) -> None:
        """启动本地 FastAPI 并打开浏览器（企业版混合模式）。"""
        import threading
        try:
            import fastapi, uvicorn  # noqa: F401
        except ImportError:
            QMessageBox.information(self, "需要安装依赖", tr("web.need_dep"))
            return

        from web_ui.app import create_app
        port = 8200
        try:
            t = threading.Thread(
                target=lambda: uvicorn.run(create_app(), host="127.0.0.1",
                                           port=port, log_level="warning"),
                daemon=True)
            t.start()
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "启动失败", f"{type(e).__name__}: {e}")
            return
        import webbrowser
        webbrowser.open(f"http://127.0.0.1:{port}")
        self.statusBar().showMessage(tr("web.started", port=port), 8000)

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
        if price is not None and price == price:  # 过滤 NaN
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
        # 决策记录/模拟盘/分析日志为懒加载tab：确保已创建再刷新，避免 AttributeError
        cur = self.tabs.currentIndex()
        for idx, attr in ((11, "history_tab"), (5, "paper_tab"), (12, "analysis_log_tab")):
            if idx in self._lazy_tabs and idx not in self._created:
                _name, _cls = self._lazy_tabs[idx]
                try:
                    _tab = _cls()
                    self.tabs.removeTab(idx)
                    self.tabs.insertTab(idx, _tab, _name)
                    self._created[idx] = _tab
                    setattr(self, attr, _tab)
                except Exception:  # noqa: BLE001 - 懒加载失败不影响分析流程
                    pass
        # 与懒加载一致：替换占位页后恢复当前页，避免用户被弹到相邻页
        if self.tabs.currentIndex() != cur:
            self.tabs.setCurrentIndex(cur)
        ht = getattr(self, "history_tab", None) or self._created.get(11)
        if ht is not None:
            try:
                ht.refresh()
            except Exception:  # noqa: BLE001
                pass
        pt = getattr(self, "paper_tab", None) or self._created.get(5)
        if pt is not None:
            try:
                pt.refresh()
            except Exception:  # noqa: BLE001
                pass
        alt = getattr(self, "analysis_log_tab", None) or self._created.get(12)
        if alt is not None:
            try:
                alt.refresh()
            except Exception:  # noqa: BLE001
                pass
        self._log_analysis(result)
        state = result.get("state") or {}
        ticker = state.get("ticker")
        # 哈希链审计：每次 AI 分析留痕（失败不影响流程）
        try:
            from security.audit_ledger import append as _aud
            _aud("ai", "analysis", f"ticker={ticker or '?'}")
        except Exception:
            pass
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
