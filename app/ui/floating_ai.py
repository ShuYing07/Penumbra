# -*- coding: utf-8 -*-
"""浮动 AI 助手（模块五 · 参考华泰 AI 涨乐意图驱动 / Robinhood 渐进式披露）。

- 右下角悬浮 48px 半透明圆形按钮（玻璃拟态），点击展开对话面板；
- 面板自动感知当前选中的股票（main_window.current_ticker），
  用户无需重复说「我在看茅台」；
- 自然语言指令（"帮我分析茅台""运行回测"）经 main_window 路由到
  对话分析页的 Agent 链路处理；
- 支持 Ctrl+Shift+A 快捷键唤起。
"""
from __future__ import annotations

import logging

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QLineEdit,
                             QPushButton, QVBoxLayout, QWidget)

from app.ui.ui_theme import ACCENT, BORDER, TEXT_MAIN, TEXT_SUB

log = logging.getLogger("stockai.ui.floatingai")

PANEL_STYLE = f"""
QFrame#aiPanel {{
    background: rgba(15,18,26,0.92);
    border: 1px solid rgba(0,180,216,0.28);
    border-radius: 14px;
}}
QLineEdit {{
    background: rgba(20,24,32,0.9);
    border: 1px solid {BORDER};
    border-radius: 8px; padding: 7px 10px; color: {TEXT_MAIN};
}}
QLineEdit:focus {{ border: 1px solid {ACCENT}; }}
QPushButton#sendBtn {{
    background: {ACCENT}; color: #0A0C10; border: none;
    border-radius: 8px; padding: 6px 14px; font-weight: bold;
}}
QPushButton#sendBtn:hover {{ background: #33C3E0; }}
"""


class FloatingAIButton(QPushButton):
    """右下角半透明悬浮按钮（48px 圆形玻璃拟态）。"""

    def __init__(self, parent=None):
        super().__init__("✨", parent)
        self.setFixedSize(48, 48)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("AI 助手（Ctrl+Shift+A）")
        self.setStyleSheet(f"""
            QPushButton {{
                background: rgba(20,24,32,0.72);
                border: 1px solid rgba(0,180,216,0.35);
                border-radius: 24px;
                font-size: 20px;
            }}
            QPushButton:hover {{
                background: rgba(0,180,216,0.25);
                border: 1px solid {ACCENT};
            }}
        """)


class FloatingAIPanel(QFrame):
    """悬浮对话面板：感知当前股票 + 自然语言指令。"""

    submit = pyqtSignal(str)  # query

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("aiPanel")
        self.setStyleSheet(PANEL_STYLE)
        self.setFixedWidth(340)
        self._build()

    def _build(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)

        head = QHBoxLayout()
        title = QLabel("✨ 疏影 AI 助手")
        title.setStyleSheet(f"font-size:13px; font-weight:bold; color:{TEXT_MAIN};")
        self.lbl_ctx = QLabel("")
        self.lbl_ctx.setStyleSheet(f"font-size:11px; color:{ACCENT};")
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(self.lbl_ctx)
        lay.addLayout(head)

        hint = QLabel("自然语言即可：\n「分析 600519」「看看茅台的新闻」「对比宁德和比亚迪」")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"font-size:11px; color:{TEXT_SUB};")
        lay.addWidget(hint)

        row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("输入问题，回车发送…")
        self.input.returnPressed.connect(self._send)
        btn = QPushButton("发送")
        btn.setObjectName("sendBtn")
        btn.clicked.connect(self._send)
        row.addWidget(self.input, 1)
        row.addWidget(btn)
        lay.addLayout(row)

    def set_context(self, ticker: str = "", name: str = "") -> None:
        """感知当前股票并展示在面板顶部。"""
        if ticker:
            label = name or ticker
            self.lbl_ctx.setText(f"🎯 正在查看：{label}")
        else:
            self.lbl_ctx.setText("未选中标的")

    def _send(self) -> None:
        q = self.input.text().strip()
        if q:
            self.submit.emit(q)
            self.input.clear()


class FloatingAI(QWidget):
    """右下角悬浮助手整体：按钮 + 面板（依附主窗口，跟随窗口移动）。"""

    def __init__(self, main_window):
        super().__init__(main_window)
        self._main = main_window
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._panel_visible = False

        self.btn = FloatingAIButton(self)
        self.btn.clicked.connect(self.toggle_panel)

        self.panel = FloatingAIPanel(self)
        self.panel.submit.connect(self._on_submit)
        self.panel.hide()

    def toggle_panel(self) -> None:
        self._panel_visible = not self._panel_visible
        self.panel.setVisible(self._panel_visible)
        if self._panel_visible:
            self.panel.raise_()
            self.panel.input.setFocus()
        self._place()

    def show_panel(self) -> None:
        self._panel_visible = True
        self.panel.show()
        self.panel.raise_()
        self.panel.input.setFocus()
        self._place()

    def hide_panel(self) -> None:
        self._panel_visible = False
        self.panel.hide()

    def refresh_context(self) -> None:
        tk = getattr(self._main, "current_ticker", "") or ""
        nm = getattr(self._main, "current_ticker_name", "") or ""
        self.panel.set_context(tk, nm)

    def _on_submit(self, query: str) -> None:
        # 路由到主窗口：切到对话分析页并交给 Agent 链路
        try:
            self._main._on_ai_query(query)
        except Exception as e:  # noqa: BLE001
            log.warning("floating AI 指令处理失败: %s", e)

    def _place(self) -> None:
        """置于主窗口右下角（按钮 16px 边距，面板悬于按钮上方）。"""
        w = self._main.width()
        h = self._main.height()
        self.btn.move(w - 48 - 16, h - 48 - 16)
        if self._panel_visible:
            ph = self.panel.height()
            self.panel.move(w - 340 - 16, h - ph - 48 - 24)
