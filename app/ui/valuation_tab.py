# -*- coding: utf-8 -*-
"""Swarm 估值标签页：多 Agent 分任务估值 + 辩论对齐收敛。

数据来源：优先本地缓存（core.data.cache），无缓存用演示基本面——不阻塞、不联网。
估值仅为数据统计演示，输出强制附加合规声明。
"""
from __future__ import annotations

import logging

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QPushButton,
                             QTextEdit, QVBoxLayout, QWidget)

log = logging.getLogger("stockai.ui.valuation")


class ValuationTab(QWidget):
    """LLM Swarm 估值（演示引擎，离线可用）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)

        tip = QLabel(
            "LLM Swarm 估值：DCF / 相对估值 / 情绪动量 三任务 × 3 Agent，"
            "辩论对齐后比例投票收敛。数据来自本地缓存或演示值，不联网。")
        tip.setWordWrap(True)
        tip.setStyleSheet("color:#8B949E; font-size:12px;")
        lay.addWidget(tip)

        row = QHBoxLayout()
        row.addWidget(QLabel("代码："))
        self.input = QComboBox()
        self.input.setEditable(True)
        self.input.addItems(["SH600519", "AAPL", "000300", "0700.HK"])
        self.input.setCurrentText("SH600519")
        self.input.setMinimumWidth(160)
        row.addWidget(self.input)
        self.run_btn = QPushButton("⚡ 运行 Swarm 估值")
        self.run_btn.setStyleSheet(
            "background-color:#00E5FF; color:#0A0E17; border-radius:8px; padding:6px 14px;")
        self.run_btn.clicked.connect(self._run)
        row.addWidget(self.run_btn)
        row.addStretch(1)
        lay.addLayout(row)

        self.out = QTextEdit()
        self.out.setReadOnly(True)
        self.out.setStyleSheet(
            "background-color:#131722; border:1px solid #1E2530; border-radius:12px;"
            "color:#E6EDF3; font-family:Consolas; padding:8px;")
        lay.addWidget(self.out, 1)

        self._set_demo("SH600519")

    def _set_demo(self, ticker: str) -> None:
        self.out.setPlainText(
            f"输入股票代码（如 {ticker}）并点击「运行 Swarm 估值」。\n\n"
            "> 本估值由 Swarm 框架演示生成，仅供研究学习，不构成任何投资建议。")

    def _facts(self, ticker: str) -> dict:
        """从本地缓存构造基本面；缺失用演示值（标注 demo）。"""
        try:
            from core.data import cache
            bars = cache.load_bars(ticker)
            closes = bars["close"].dropna().tolist() if bars is not None else []
        except Exception:  # noqa: BLE001
            closes = []
        if closes:
            close = float(closes[-1])
            ret5 = (closes[-1] / closes[-6] - 1) if len(closes) >= 6 else 0.0
            eps = round(close * 0.03, 2)   # 演示 EPS（约 3% 收益率）
            return {"close": close, "eps": eps, "growth_pct": 8.0,
                    "discount_rate": 0.10, "pe_ttm": 20.0, "peer_pe": 22.0,
                    "momentum": round(min(0.3, max(-0.3, ret5)), 3),
                    "sentiment": 0.2, "_source": "cache+demo"}
        return {"close": 100.0, "eps": 5.0, "growth_pct": 8.0,
                "discount_rate": 0.10, "pe_ttm": 20.0, "peer_pe": 22.0,
                "momentum": 0.12, "sentiment": 0.3, "_source": "demo"}

    def _run(self) -> None:
        ticker = self.input.currentText().strip() or "SH600519"
        try:
            from valuation_swarm import SwarmEstimator, DebateAlignment
            facts = self._facts(ticker)
            sw = SwarmEstimator()
            da = DebateAlignment()
            out = sw.run_with_alignment(ticker, facts, alignment=da)
            header = f"（数据源：{facts.get('_source', '?')}）"
            self.out.setPlainText(f"{header}\n\n{out['report']}")
        except Exception as e:  # noqa: BLE001
            log.warning("Swarm 估值失败 %s: %s", ticker, e)
            self.out.setPlainText(f"运行失败：{type(e).__name__}: {e}\n\n"
                                  "估值框架可用性自检：\n"
                                  "python -m valuation_swarm.debate_alignment")
