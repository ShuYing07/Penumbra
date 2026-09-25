# -*- coding: utf-8 -*-
"""疏影·知微 全局主题：色彩、字体、QSS。"""
from __future__ import annotations

from pathlib import Path

# ---------- 色彩 ----------
BG_MAIN = "#0A0E17"       # 主背景
BG_CARD = "#131722"       # 卡片背景
BG_HOVER = "#1A2030"      # 悬停
BORDER = "#1E2530"        # 边框
TEXT_MAIN = "#E6EDF3"     # 主文字
TEXT_SUB = "#8B949E"      # 次要文字
UP = "#00C853"            # 上涨绿
DOWN = "#FF1744"          # 下跌红
ACCENT = "#00E5FF"        # 主题青
WARN = "#FFA726"          # 警告橙

# ---------- 字体 ----------
FONT_FAMILY = "Microsoft YaHei UI, PingFang SC, Segoe UI, sans-serif"
FONT_MONO = "JetBrains Mono, Consolas, Cascadia Code, monospace"
FONT_SIZE_BASE = 13
FONT_SIZE_SMALL = 11
FONT_SIZE_LARGE = 18

# ---------- QSS ----------
QSS = f"""
QMainWindow, QDialog {{
    background-color: {BG_MAIN};
    color: {TEXT_MAIN};
    font-family: {FONT_FAMILY};
    font-size: {FONT_SIZE_BASE}px;
}}

QWidget {{
    color: {TEXT_MAIN};
    font-family: {FONT_FAMILY};
}}

/* 顶部搜索栏 */
QLineEdit {{
    background-color: {BG_CARD};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 6px 12px;
    color: {TEXT_MAIN};
    selection-background-color: {ACCENT};
}}
QLineEdit:focus {{
    border: 1px solid {ACCENT};
}}

/* 按钮 */
QPushButton {{
    background-color: {BG_CARD};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 6px 14px;
    color: {TEXT_MAIN};
}}
QPushButton:hover {{
    background-color: {BG_HOVER};
    border: 1px solid {ACCENT};
}}
QPushButton:pressed {{
    background-color: {ACCENT};
    color: {BG_MAIN};
}}
QPushButton:checked {{
    background-color: rgba(0,229,255,0.12);
    border: 1px solid {ACCENT};
    color: {ACCENT};
}}

/* 标签页 */
QTabWidget::pane {{
    border: 1px solid {BORDER};
    border-radius: 8px;
    background: {BG_CARD};
    top: -1px;
}}
QTabBar::tab {{
    background: transparent;
    color: {TEXT_SUB};
    padding: 8px 16px;
    border: 1px solid transparent;
    border-bottom: none;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    margin-right: 2px;
}}
QTabBar::tab:selected {{
    background: {BG_CARD};
    color: {ACCENT};
    border: 1px solid {BORDER};
    border-bottom: 2px solid {ACCENT};
}}
QTabBar::tab:hover:!selected {{
    color: {TEXT_MAIN};
    background: {BG_HOVER};
}}

/* 表格 */
QTableView, QTableWidget, QListView, QTreeView {{
    background: {BG_CARD};
    alternate-background-color: {BG_HOVER};
    border: 1px solid {BORDER};
    border-radius: 8px;
    gridline-color: {BORDER};
    selection-background-color: rgba(0,229,255,0.15);
    selection-color: {TEXT_MAIN};
}}
QHeaderView::section {{
    background: {BG_MAIN};
    color: {TEXT_SUB};
    padding: 6px;
    border: none;
    border-bottom: 1px solid {BORDER};
    font-weight: bold;
}}

/* 下拉框 */
QComboBox {{
    background: {BG_CARD};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 5px 10px;
    color: {TEXT_MAIN};
}}
QComboBox:hover {{ border: 1px solid {ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 20px; }}
QComboBox QAbstractItemView {{
    background: {BG_CARD};
    border: 1px solid {BORDER};
    selection-background-color: rgba(0,229,255,0.15);
}}

/* 滚动条 */
QScrollBar:vertical {{
    background: transparent; width: 8px; margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {BORDER}; border-radius: 4px; min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: {TEXT_SUB}; }}
QScrollBar:horizontal {{
    background: transparent; height: 8px; margin: 0;
}}
QScrollBar::handle:horizontal {{
    background: {BORDER}; border-radius: 4px; min-width: 30px;
}}

/* 菜单 */
QMenuBar {{
    background: {BG_MAIN}; color: {TEXT_MAIN};
    border-bottom: 1px solid {BORDER};
}}
QMenuBar::item {{ padding: 6px 12px; background: transparent; }}
QMenuBar::item:selected {{ background: {BG_HOVER}; }}
QMenu {{
    background: {BG_CARD}; border: 1px solid {BORDER};
    border-radius: 8px; padding: 4px;
}}
QMenu::item {{ padding: 6px 20px; border-radius: 4px; }}
QMenu::item:selected {{ background: rgba(0,229,255,0.15); }}

/* 状态栏 */
QStatusBar {{
    background: {BG_MAIN}; color: {TEXT_SUB};
    border-top: 1px solid {BORDER};
}}
QStatusBar::item {{ border: none; }}

/* 分组框 */
QGroupBox {{
    border: 1px solid {BORDER}; border-radius: 12px;
    margin-top: 12px; padding-top: 12px;
    color: {TEXT_SUB}; font-weight: bold;
}}
QGroupBox::title {{
    subcontrol-origin: margin; left: 12px; padding: 0 6px;
}}

/* 文本区 */
QTextEdit, QPlainTextEdit, QTextBrowser {{
    background: {BG_CARD}; border: 1px solid {BORDER}; border-radius: 8px;
    color: {TEXT_MAIN};
}}

/* 分割器 */
QSplitter::handle {{ background: {BORDER}; }}
QSplitter::handle:horizontal {{ width: 2px; }}
QSplitter::handle:vertical {{ height: 2px; }}

/* 工具提示 */
QToolTip {{
    background: {BG_CARD}; color: {TEXT_MAIN};
    border: 1px solid {ACCENT}; border-radius: 4px; padding: 4px 8px;
}}

/* 消息框 */
QMessageBox, QInputDialog {{
    background: {BG_MAIN};
}}

/* 复选框/单选 */
QCheckBox, QRadioButton {{ color: {TEXT_MAIN}; spacing: 6px; }}
QCheckBox::indicator, QRadioButton::indicator {{ width: 16px; height: 16px; }}

/* 进度条 */
QProgressBar {{
    background: {BG_CARD}; border: 1px solid {BORDER};
    border-radius: 4px; text-align: center; color: {TEXT_MAIN};
}}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 3px; }}
"""


def apply_theme(app) -> None:
    """对 QApplication 应用全局 QSS。"""
    app.setStyleSheet(QSS)
