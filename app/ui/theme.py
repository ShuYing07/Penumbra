# -*- coding: utf-8 -*-
"""暗色金融终端主题：全局 QSS 深色配色，降低长时间看盘视觉疲劳。

调用：在创建 QApplication 后 `apply_dark_theme(app)`。
配色参考主流专业金融终端（深灰底 + 青蓝强调色），文字高对比。
"""
from __future__ import annotations

from PyQt6.QtWidgets import QApplication

# 色板
_BG = "#1e1f22"        # 主背景
_PANEL = "#2b2d30"     # 面板/控件底
_PANEL2 = "#34373b"    # 悬浮/hover
_BORDER = "#3f4145"
_FG = "#e6e6e6"        # 主文字
_MUTED = "#9aa0a6"     # 次要文字
_ACCENT = "#3da9fc"    # 青蓝强调
_GREEN = "#26c07a"     # 涨/多（中国习惯红涨，这里用中性色区分）
_RED = "#e5534b"


def _qss() -> str:
    return f"""
    QWidget {{
        background-color: {_BG};
        color: {_FG};
        font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
        font-size: 13px;
    }}
    QMainWindow, QDialog {{ background-color: {_BG}; }}
    QTabWidget::pane {{
        border: 1px solid {_BORDER};
        background-color: {_BG};
        top: -1px;
    }}
    QTabBar::tab {{
        background: {_PANEL};
        color: {_MUTED};
        padding: 7px 16px;
        border: 1px solid {_BORDER};
        border-bottom: none;
        border-top-left-radius: 4px;
        border-top-right-radius: 4px;
    }}
    QTabBar::tab:selected {{ background: {_BG}; color: {_ACCENT}; font-weight: 600; }}
    QTabBar::tab:hover {{ color: {_FG}; }}
    QPushButton {{
        background-color: {_PANEL2};
        color: {_FG};
        border: 1px solid {_BORDER};
        border-radius: 4px;
        padding: 6px 16px;
    }}
    QPushButton:hover {{ background-color: {_ACCENT}; color: #ffffff; }}
    QPushButton:pressed {{ background-color: #2b86d4; }}
    QPushButton:disabled {{ color: {_MUTED}; background-color: {_PANEL}; }}
    QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
        background-color: {_PANEL};
        color: {_FG};
        border: 1px solid {_BORDER};
        border-radius: 4px;
        padding: 4px 8px;
        selection-background-color: {_ACCENT};
    }}
    QLineEdit:focus, QComboBox:focus {{ border: 1px solid {_ACCENT}; }}
    QTableWidget, QTableView, QTreeWidget, QListView {{
        background-color: {_PANEL};
        alternate-background-color: {_PANEL2};
        color: {_FG};
        gridline-color: {_BORDER};
        border: 1px solid {_BORDER};
    }}
    QHeaderView::section {{
        background-color: {_PANEL2};
        color: {_MUTED};
        padding: 5px;
        border: none;
        border-right: 1px solid {_BORDER};
        border-bottom: 1px solid {_BORDER};
    }}
    QComboBox QAbstractItemView {{
        background-color: {_PANEL};
        color: {_FG};
        selection-background-color: {_ACCENT};
    }}
    QScrollBar:vertical {{
        background: {_BG}; width: 10px; margin: 0;
    }}
    QScrollBar::handle:vertical {{ background: {_PANEL2}; border-radius: 5px; min-height: 30px; }}
    QScrollBar::handle:vertical:hover {{ background: {_ACCENT}; }}
    QScrollBar:horizontal {{ background: {_BG}; height: 10px; margin: 0; }}
    QScrollBar::handle:horizontal {{ background: {_PANEL2}; border-radius: 5px; min-width: 30px; }}
    QStatusBar {{ background-color: {_PANEL}; color: {_MUTED}; }}
    QLabel {{ background: transparent; }}
    QToolTip {{
        background-color: {_PANEL2}; color: {_FG};
        border: 1px solid {_ACCENT};
    }}
    """


def apply_dark_theme(app: QApplication) -> None:
    """对 QApplication 应用全局暗色 QSS。任何异常都不阻断启动。"""
    try:
        app.setStyleSheet(_qss())
    except Exception:  # noqa: BLE001
        pass
