# -*- coding: utf-8 -*-
"""多空辩论标签页：左栏看多逻辑，右栏看空逻辑。

复用现有 core.agents.graph.run_analysis，结果取 bull_case / bear_case。
合规定位：仅为多空逻辑的客观并列展示，不构成任何投资建议。
"""
from __future__ import annotations

import logging

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QSplitter,
    QTextEdit, QVBoxLayout, QWidget,
)

log = logging.getLogger("stockai.ui.debate")


class _DebateWorker(QThread):
    done = pyqtSignal(dict)
    err = pyqtSignal(str)

    def __init__(self, ticker: str):
        super().__init__()
        self.ticker = ticker

    def run(self):
        try:
            from core.agents.graph import run_analysis
            out = run_analysis(self.ticker, progress_cb=None)
            self.done.emit(out.get("state", {}))
        except Exception as e:  # noqa: BLE001
            log.exception("多空辩论失败")
            self.err.emit(str(e))


class DebateTab(QWidget):
    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)

        top = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("输入股票代码，如 SH600519 / AAPL")
        self.btn = QPushButton("开始多空辩论")
        self.btn.clicked.connect(self._go)
        top.addWidget(QLabel("标的："))
        top.addWidget(self.input, 1)
        top.addWidget(self.btn)
        lay.addLayout(top)

        self.status = QLabel("")
        self.status.setStyleSheet("color:#8B949E;")
        lay.addWidget(self.status)

        split = QSplitter(Qt.Orientation.Horizontal)
        # 左：看多（绿）
        left = QWidget(); ll = QVBoxLayout(left)
        ll.addWidget(QLabel("📈 看多逻辑（绿色）"))
        self.bull = QTextEdit(); self.bull.setReadOnly(True)
        self.bull.setStyleSheet("border:1px solid #00C853; border-radius:6px;")
        ll.addWidget(self.bull)
        # 右：看空（红）
        right = QWidget(); rl = QVBoxLayout(right)
        rl.addWidget(QLabel("📉 看空/风险逻辑（红色）"))
        self.bear = QTextEdit(); self.bear.setReadOnly(True)
        self.bear.setStyleSheet("border:1px solid #FF1744; border-radius:6px;")
        rl.addWidget(self.bear)
        split.addWidget(left); split.addWidget(right)
        split.setStretchFactor(0, 1); split.setStretchFactor(1, 1)
        lay.addWidget(split, 1)

        lay.addWidget(QLabel("⚠️ 该分析仅为逻辑推演与数据罗列，不构成投资建议。"))

    def _go(self):
        from core.data.service import normalize_ticker
        raw = self.input.text().strip().upper()
        if not raw:
            self.status.setText("请输入股票代码")
            return
        ticker = normalize_ticker(raw)
        if ticker != raw:
            self.input.setText(ticker)
        self.btn.setEnabled(False)
        self.status.setText("AI 正在并行展开多空分析，通常需 30~90 秒…")
        self._w = _DebateWorker(ticker)
        self._w.done.connect(self._show)
        self._w.err.connect(self._fail)
        self._w.start()

    def _show(self, state: dict):
        bull = state.get("bull_case") or []
        bear = state.get("bear_case") or []
        self.bull.setPlainText(
            "⚠️ 该分析仅为逻辑推演，不构成投资建议\n\n"
            + ("\n".join(f"• {x}" for x in bull) if bull else "（无看多结论）"))
        self.bear.setPlainText(
            "⚠️ 该分析仅为逻辑推演，不构成投资建议\n\n"
            + ("\n".join(f"• {x}" for x in bear) if bear else "（无看空结论）"))
        self.status.setText("辩论完成（左侧看多 / 右侧看空，仅供研究）")
        self.btn.setEnabled(True)

    def _fail(self, msg):
        self.status.setText("分析失败：" + msg)
        self.btn.setEnabled(True)
