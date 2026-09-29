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
        # 左：看多（绿，仅用于涨跌语义）
        left = QWidget(); ll = QVBoxLayout(left)
        bull_title = QLabel("📈 看多逻辑")
        bull_title.setStyleSheet(
            "font-size:15px; font-weight:bold; color:#00C853;"
            "border-left:3px solid #00C853; padding-left:8px;")
        ll.addWidget(bull_title)
        self.bull = QTextEdit(); self.bull.setReadOnly(True)
        self.bull.setStyleSheet(
            "border:1px solid rgba(0,200,83,0.35); border-radius:10px;"
            "background:rgba(0,200,83,0.06); padding:8px;")
        ll.addWidget(self.bull)
        # 右：看空（红，仅用于涨跌语义）
        right = QWidget(); rl = QVBoxLayout(right)
        bear_title = QLabel("📉 看空/风险逻辑")
        bear_title.setStyleSheet(
            "font-size:15px; font-weight:bold; color:#FF1744;"
            "border-left:3px solid #FF1744; padding-left:8px;")
        rl.addWidget(bear_title)
        self.bear = QTextEdit(); self.bear.setReadOnly(True)
        self.bear.setStyleSheet(
            "border:1px solid rgba(255,23,68,0.35); border-radius:10px;"
            "background:rgba(255,23,68,0.06); padding:8px;")
        rl.addWidget(self.bear)
        split.addWidget(left); split.addWidget(right)
        split.setStretchFactor(0, 1); split.setStretchFactor(1, 1)
        lay.addWidget(split, 1)

        # 风控审查（橙色，风险语义）
        self.risk = QLabel("🛡️ 风控审查：辩论完成后显示")
        self.risk.setWordWrap(True)
        self.risk.setStyleSheet(
            "color:#FFA726; background:rgba(255,167,38,0.08);"
            "border:1px solid rgba(255,167,38,0.35); border-radius:10px; padding:10px;")
        lay.addWidget(self.risk)

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
        self.bull.setHtml(self._cards(bull, "看多", "#00C853"))
        self.bear.setHtml(self._cards(bear, "看空", "#FF1744"))
        # 风控审查：橙色标注高不确定论点（辩论为观点展示，不构成建议）
        try:
            risk_txt = state.get("risk_note") or (
                "本页为多空逻辑的客观并列展示。请自行核实数据来源，"
                "历史表现不代表未来，任何结论都不构成投资建议。")
            self.risk.setText(f"🛡️ 风控审查：{risk_txt}")
        except Exception:  # noqa: BLE001
            pass
        self.status.setText("辩论完成（左侧看多 / 右侧看空，仅供研究）")
        self.btn.setEnabled(True)

    @staticmethod
    def _cards(items, side: str, color: str) -> str:
        """Claim-level 卡片渲染：论点标题加粗 + 论据次要文字 + 来源标注。"""
        if not items:
            return (f"<div style='color:#8B949E;padding:12px'>"
                    f"（无{side}结论）</div>")
        parts = [f"<div style='color:#8B949E;font-size:12px;padding-bottom:6px'>"
                 f"⚠️ 该分析仅为逻辑推演，不构成投资建议</div>"]
        for i, x in enumerate(items, 1):
            # 论点通常为单段文本：拆标题/论据（按 "：" 或 "：")
            title, _, rest = x.partition("：") if "：" in x else (x, "", "")
            title = title if title else x
            parts.append(
                f"<div style='background:rgba(0,0,0,0.18);border-left:3px solid {color};"
                f"border-radius:8px;padding:8px 10px;margin-bottom:8px;'>"
                f"<div style='font-weight:bold;color:#E6EDF3;'>论点{i}. {title}</div>"
                f"<div style='color:#8B949E;font-size:12px;'>{(rest or '—')}</div>"
                f"<div style='color:#6B7488;font-size:11px;'>数据来源：本地行情/指标（辩论观点，非投资建议）</div>"
                f"</div>")
        return "".join(parts)

    def _fail(self, msg):
        self.status.setText("分析失败：" + msg)
        self.btn.setEnabled(True)
