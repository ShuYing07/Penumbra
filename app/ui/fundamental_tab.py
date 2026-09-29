# -*- coding: utf-8 -*-
"""基本面分析标签页（模块九）：估值指标卡片 + 财务健康度评分 + 同行对比。
0.8.0 增强：财报摘要卡片（关键指标/多期对比）+ 财务比率 + 5 年 DCF 敏感性分析。"""
from __future__ import annotations

import logging

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (QHBoxLayout, QLabel, QLineEdit, QPushButton,
                             QScrollArea, QTextEdit, QVBoxLayout, QWidget)

from core.data import service

log = logging.getLogger("stockai.ui.fundamental")


class FundamentalTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)

        top = QHBoxLayout()
        top.addWidget(QLabel("代码："))
        self.input = QLineEdit()
        self.input.setPlaceholderText("如 600519 / AAPL / 0700.HK")
        self.input.returnPressed.connect(self._run)
        top.addWidget(self.input, 1)
        self.btn = QPushButton("分析基本面")
        self.btn.clicked.connect(self._run)
        top.addWidget(self.btn)
        lay.addLayout(top)

        self.out = QTextEdit()
        self.out.setReadOnly(True)
        self.out.setText("输入股票代码，点击「分析基本面」。\n"
                         "展示：财务健康度评分、营收/净利增速、毛利率、估值指标、同行对比。")
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.out)
        lay.addWidget(scroll, 1)

    def _run(self) -> None:
        code = self.input.text().strip().upper()
        if not code:
            return
        self.btn.setEnabled(False)
        self.out.setText("⏳ 正在获取财报与估值数据…")

        class _W(QThread):
            done = pyqtSignal(object)

            def run(self):
                try:
                    from core.financial_report_parser import build_report_card_html
                    self.done.emit(build_report_card_html(code))
                except Exception as e:  # noqa: BLE001
                    self.done.emit(f"<span style='color:#FF1744'>分析失败：{e}</span>")

        w = _W()
        w.done.connect(lambda html: (self.out.setHtml(html), self.btn.setEnabled(True)))
        w.start()

