# -*- coding: utf-8 -*-
"""疏影·知微 全局主题：色彩、字体、QSS（暗色玻璃态 + 浅色舒适态，一键切换）。

设计参考（调研 OpenBB Workspace / FreqUI / Stonks / Glass Home 后吸收）：
- 暗色主背景 #0A0E17（减少长时间盯盘疲劳）；卡片半透明玻璃态 + 1px 青色细边；
- 涨 #00C853 / 跌 #FF1744（国际习惯）与国内习惯（涨红跌绿）由各页自行选择；
- 主题强调 #00E5FF 赛博青；警告 #FFA726；
- 提供 dark / light 两套完整 token，apply_theme(app, theme) 一键切换全局 QSS。
"""
from __future__ import annotations

from pathlib import Path

# ---------------------------------------------------------------------------
# 主题 Token 表（dark / light 两套完整配色）
# ---------------------------------------------------------------------------
THEMES: dict[str, dict[str, str]] = {
    "dark": {
        "name": "暗色 · 玻璃态",
        "bg_main": "#0A0E17",          # 主背景（深空黑）
        "bg_card": "rgba(19,23,34,0.88)",  # 玻璃拟态卡片
        "bg_card_solid": "#131722",    # 卡片实体色（表格等需不透明背景的场景）
        "bg_hover": "#1A2030",
        "border": "#1E2530",
        "border_glow": "rgba(0,229,255,0.15)",
        "text_main": "#E6EDF3",
        "text_sub": "#8B949E",
        "up": "#00C853",
        "down": "#FF1744",
        "accent": "#00E5FF",
        "warn": "#FFA726",
        "shadow": "rgba(0,0,0,0.4)",
    },
    "light": {
        "name": "浅色 · 舒适",
        "bg_main": "#F5F7FA",
        "bg_card": "rgba(255,255,255,0.92)",
        "bg_card_solid": "#FFFFFF",
        "bg_hover": "#EAEEF4",
        "border": "#D5DDE8",
        "border_glow": "rgba(0,133,186,0.18)",
        "text_main": "#1B2430",
        "text_sub": "#5B6B7C",
        "up": "#00A84D",
        "down": "#E0354B",
        "accent": "#0085BA",
        "warn": "#D97B06",
        "shadow": "rgba(0,0,0,0.12)",
    },
}

_current: str = "dark"


def current_theme() -> str:
    return _current


def toggle_theme() -> str:
    """切换明暗主题并返回新主题名。"""
    global _current
    _current = "light" if _current == "dark" else "dark"
    return _current


def set_theme(name: str) -> None:
    global _current
    if name in THEMES:
        _current = name


# 保持向后兼容的模块级常量（默认暗色值，旧模块直接 import）
BG_MAIN = THEMES["dark"]["bg_main"]
BG_CARD = THEMES["dark"]["bg_card_solid"]
BG_HOVER = THEMES["dark"]["bg_hover"]
BORDER = THEMES["dark"]["border"]
TEXT_MAIN = THEMES["dark"]["text_main"]
TEXT_SUB = THEMES["dark"]["text_sub"]
UP = THEMES["dark"]["up"]
DOWN = THEMES["dark"]["down"]
ACCENT = THEMES["dark"]["accent"]
WARN = THEMES["dark"]["warn"]

# ---------- 字体 ----------
FONT_FAMILY = "Microsoft YaHei UI, PingFang SC, Segoe UI, sans-serif"
FONT_MONO = "JetBrains Mono, Consolas, Cascadia Code, monospace"
FONT_SIZE_BASE = 13
FONT_SIZE_SMALL = 11
FONT_SIZE_LARGE = 18

# 玻璃态常量（QSS 语法内的透明度由各主题 token 决定）
RADIUS_CARD = 16
RADIUS_BTN = 10
RADIUS_INPUT = 10


def build_qss(theme_name: str = "") -> str:
    """按主题生成全局 QSS。"""
    t = THEMES[theme_name or _current]
    bg = t["bg_main"]
    card = t["bg_card"]
    card_solid = t["bg_card_solid"]
    hover = t["bg_hover"]
    border = t["border"]
    text = t["text_main"]
    sub = t["text_sub"]
    accent = t["accent"]
    glow = t["border_glow"]
    return f"""
QMainWindow, QDialog {{
    background-color: {bg};
    color: {text};
    font-family: {FONT_FAMILY};
    font-size: {FONT_SIZE_BASE}px;
}}

QWidget {{ color: {text}; font-family: {FONT_FAMILY}; }}

/* 卡片：玻璃拟态（半透明背景 + 细边框 + 大圆角） */
QFrame#glassCard, QFrame[glass="true"] {{
    background: {card};
    border: 1px solid {glow};
    border-radius: {RADIUS_CARD}px;
}}

/* 顶部搜索栏 / 输入 */
QLineEdit {{
    background-color: {card};
    border: 1px solid {border};
    border-radius: {RADIUS_INPUT}px;
    padding: 6px 12px;
    color: {text};
    selection-background-color: {accent};
}}
QLineEdit:focus {{ border: 1px solid {accent}; }}

/* 按钮 */
QPushButton {{
    background-color: {card};
    border: 1px solid {border};
    border-radius: {RADIUS_BTN}px;
    padding: 6px 14px;
    color: {text};
}}
QPushButton:hover {{
    background-color: {hover};
    border: 1px solid {accent};
}}
QPushButton:pressed {{ background-color: {accent}; color: {bg}; }}
QPushButton:checked {{
    background-color: rgba(0,229,255,0.12);
    border: 1px solid {accent};
    color: {accent};
}}

/* 标签页 */
QTabWidget::pane {{
    border: 1px solid {border};
    border-radius: 8px;
    background: {card_solid};
    top: -1px;
}}
QTabBar::tab {{
    background: transparent;
    color: {sub};
    padding: 8px 16px;
    border: 1px solid transparent;
    border-bottom: none;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    margin-right: 2px;
}}
QTabBar::tab:selected {{
    background: {card_solid};
    color: {accent};
    border: 1px solid {border};
    border-bottom: 2px solid {accent};
}}
QTabBar::tab:hover:!selected {{ color: {text}; background: {hover}; }}

/* 表格 */
QTableView, QTableWidget, QListView, QTreeView {{
    background: {card_solid};
    alternate-background-color: {hover};
    border: 1px solid {border};
    border-radius: 8px;
    gridline-color: {border};
    selection-background-color: rgba(0,229,255,0.15);
    selection-color: {text};
}}
QHeaderView::section {{
    background: {bg};
    color: {sub};
    padding: 6px;
    border: none;
    border-bottom: 1px solid {border};
    font-weight: bold;
}}

/* 下拉框 */
QComboBox {{
    background: {card};
    border: 1px solid {border};
    border-radius: {RADIUS_INPUT}px;
    padding: 5px 10px;
    color: {text};
}}
QComboBox:hover {{ border: 1px solid {accent}; }}
QComboBox::drop-down {{ border: none; width: 20px; }}
QComboBox QAbstractItemView {{
    background: {card_solid};
    border: 1px solid {border};
    selection-background-color: rgba(0,229,255,0.15);
}}

/* 滚动条 */
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {border}; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {sub}; }}
QScrollBar:horizontal {{ background: transparent; height: 8px; margin: 0; }}
QScrollBar::handle:horizontal {{ background: {border}; border-radius: 4px; min-width: 30px; }}

/* 菜单 */
QMenuBar {{ background: {bg}; color: {text}; border-bottom: 1px solid {border}; }}
QMenuBar::item {{ padding: 6px 12px; background: transparent; }}
QMenuBar::item:selected {{ background: {hover}; }}
QMenu {{
    background: {card_solid}; border: 1px solid {border};
    border-radius: 8px; padding: 4px;
}}
QMenu::item {{ padding: 6px 20px; border-radius: 4px; }}
QMenu::item:selected {{ background: rgba(0,229,255,0.15); }}

/* 状态栏 */
QStatusBar {{ background: {bg}; color: {sub}; border-top: 1px solid {border}; }}
QStatusBar::item {{ border: none; }}

/* 分组框 */
QGroupBox {{
    border: 1px solid {border}; border-radius: 12px;
    margin-top: 12px; padding-top: 12px;
    color: {sub}; font-weight: bold;
}}
QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 6px; }}

/* 文本区 */
QTextEdit, QPlainTextEdit, QTextBrowser {{
    background: {card}; border: 1px solid {border}; border-radius: 8px;
    color: {text};
}}

/* 分割器 */
QSplitter::handle {{ background: {border}; }}
QSplitter::handle:horizontal {{ width: 2px; }}
QSplitter::handle:vertical {{ height: 2px; }}

/* 停靠面板（QDockWidget） */
QDockWidget {{
    color: {sub}; titlebar-close-icon: none;
}}
QDockWidget::title {{
    background: {bg}; padding: 6px 10px; border-bottom: 1px solid {border};
    color: {text}; font-weight: bold;
}}

/* 工具提示 */
QToolTip {{
    background: {card_solid}; color: {text};
    border: 1px solid {accent}; border-radius: 4px; padding: 4px 8px;
}}

/* 消息框 */
QMessageBox, QInputDialog {{ background: {bg}; }}

/* 复选框/单选 */
QCheckBox, QRadioButton {{ color: {text}; spacing: 6px; }}
QCheckBox::indicator, QRadioButton::indicator {{ width: 16px; height: 16px; }}

/* 进度条 */
QProgressBar {{
    background: {card_solid}; border: 1px solid {border};
    border-radius: 4px; text-align: center; color: {text};
}}
QProgressBar::chunk {{ background: {accent}; border-radius: 3px; }}
"""


QSS = build_qss("dark")


def apply_theme(app, theme_name: str = "") -> None:
    """对 QApplication 应用指定主题的全局 QSS（缺省用当前主题）。"""
    app.setStyleSheet(build_qss(theme_name or _current))
