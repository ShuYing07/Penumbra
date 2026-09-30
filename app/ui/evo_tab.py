# -*- coding: utf-8 -*-
"""进化追踪标签页（模块七 · 参考 EvoTraders / ReMe）。

- 上方：手动录入一笔模拟交易（代码/方向/入场/出场/数量/持仓/原因）→「记录并反思」；
- 中部：反思时间线（维度/成败/洞察）；
- 下方：风格画像 + 累计净值曲线（QPainter）。
"""
from __future__ import annotations

import logging

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import (QHBoxLayout, QLabel, QLineEdit, QPushButton,
                             QScrollArea, QSplitter, QVBoxLayout, QWidget)

from app.ui.ui_theme import ACCENT, BG_CARD, BORDER, TEXT_MAIN, TEXT_SUB

log = logging.getLogger("stockai.ui.evo")


class _EquityChart(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._curve: list[float] = []
        self.setMinimumHeight(120)

    def set_curve(self, curve: list[float]) -> None:
        self._curve = curve
        self.update()

    def paintEvent(self, _ev) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor(BG_CARD))
        if not self._curve:
            p.setPen(QColor(TEXT_SUB))
            p.drawText(QRectF(8, 8, w - 16, h - 16),
                       Qt.AlignmentFlag.AlignCenter, "暂无净值曲线，先记录几笔交易")
            return
        pad = 10
        lo, hi = min(self._curve), max(self._curve)
        rng = (hi - lo) or 1.0
        px = py = None
        for i, v in enumerate(self._curve):
            x = pad + i * (w - 2 * pad) / max(1, len(self._curve) - 1)
            y = h - pad - (v - lo) / rng * (h - 2 * pad)
            p.setPen(QPen(QColor(ACCENT), 2))
            if px is not None:
                p.drawLine(int(px), int(py), int(x), int(y))
            p.setBrush(QColor(ACCENT))
            p.drawEllipse(int(x) - 2, int(y) - 2, 4, 4)
            px, py = x, y
        p.setPen(QColor(TEXT_SUB))
        p.drawText(QRectF(pad, 2, w - 2 * pad, 18),
                   Qt.AlignmentFlag.AlignLeft,
                   f"累计净值（{len(self._curve)} 笔 · 当前 {self._curve[-1]:.2f}）")


class EvoTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        title = QLabel("自我进化追踪（ReMe 记忆 · 交易后反思）")
        title.setStyleSheet(f"color:{TEXT_MAIN};font-size:16px;font-weight:bold;")
        root.addWidget(title)

        split = QSplitter(Qt.Orientation.Vertical)

        # 录入区
        form = QWidget()
        fl = QVBoxLayout(form)
        row1 = QHBoxLayout()
        self.code = QLineEdit("600519"); self.code.setStyleSheet(_box())
        self.side = QLineEdit("多"); self.side.setStyleSheet(_box())
        self.entry = QLineEdit("300"); self.entry.setStyleSheet(_box())
        self.exit_ = QLineEdit("320"); self.exit_.setStyleSheet(_box())
        self.qty = QLineEdit("100"); self.qty.setStyleSheet(_box())
        self.hold = QLineEdit("12"); self.hold.setStyleSheet(_box())
        labels = ["代码", "方向(多/空)", "入场", "出场", "数量", "持仓天数"]
        for lbl, w in zip(labels, (self.code, self.side, self.entry,
                                   self.exit_, self.qty, self.hold)):
            row1.addWidget(QLabel(lbl))
            row1.addWidget(w)
        fl.addLayout(row1)
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("交易原因"))
        self.reason = QLineEdit("均线金叉趋势跟随")
        self.reason.setStyleSheet(_box())
        row2.addWidget(self.reason, 1)
        btn = QPushButton("记录并反思")
        btn.setStyleSheet(_btn(primary=True))
        btn.clicked.connect(self._record)
        row2.addWidget(btn)
        fl.addLayout(row2)
        split.addWidget(form)

        # 内容区
        content = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.addWidget(QLabel("反思时间线（最近 20 条）"))
        self.log_area = QScrollArea()
        self.log_area.setWidgetResizable(True)
        self.log_inner = QWidget()
        self.log_v = QVBoxLayout(self.log_inner)
        self.log_v.addStretch(1)
        self.log_area.setWidget(self.log_inner)
        self.log_area.setStyleSheet(
            f"QScrollArea{{background:{BG_CARD};border:1px solid {BORDER};"
            f"border-radius:6px;}}")
        ll.addWidget(self.log_area, 1)
        content.addWidget(left)

        right = QWidget()
        rl = QVBoxLayout(right)
        self.profile = QLabel("尚无交易记录")
        self.profile.setWordWrap(True)
        self.profile.setStyleSheet(
            f"color:{TEXT_SUB};background:{BG_CARD};border:1px solid {BORDER};"
            f"border-radius:6px;padding:8px;")
        rl.addWidget(self.profile)
        self.chart = _EquityChart()
        rl.addWidget(self.chart, 1)
        content.addWidget(right)
        content.setSizes([420, 420])
        split.addWidget(content)
        split.setStretchFactor(0, 1)
        root.addWidget(split, 1)

        self._refresh()

    def _record(self) -> None:
        from core.agents.evo_memory import record_and_reflect, \
            style_profile, equity_curve, recent_reflections
        try:
            entry = float(self.entry.text() or 0)
            exit_ = float(self.exit_.text() or 0)
            qty = float(self.qty.text() or 0)
        except ValueError:
            self.profile.setText("入场/出场/数量必须是数字")
            return
        hold = float(self.hold.text() or 0)
        pnl = (exit_ - entry) * qty
        trade = {"code": self.code.text().strip() or "600519",
                 "side": self.side.text().strip() or "多",
                 "entry": entry, "exit": exit_, "qty": qty,
                 "pnl": pnl, "hold_days": hold,
                 "reason": self.reason.text().strip()}
        out = record_and_reflect(trade)
        self._refresh()

    def _refresh(self) -> None:
        from core.agents.evo_memory import style_profile, equity_curve, \
            recent_reflections
        sp = style_profile()
        self.profile.setText("风格画像：" + sp["profile"])
        self.chart.set_curve(equity_curve())
        # 清空重建反思列表
        while self.log_v.count() > 1:
            item = self.log_v.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        refs = recent_reflections(20)
        for r in refs:
            color = "#00C853" if r["outcome"] == "win" else "#FF1744"
            lbl = QLabel(f"[{'✓' if r['outcome'] == 'win' else '✗'} "
                         f"{r['dimension']}] {r['insight']}")
            lbl.setWordWrap(True)
            lbl.setStyleSheet(
                f"color:{TEXT_MAIN};background:{BG_CARD};"
                f"border-left:3px solid {color};border-radius:4px;"
                f"padding:4px 8px;margin:2px 0;")
            self.log_v.insertWidget(0, lbl)


def _box() -> str:
    return (f"QLineEdit{{background:{BG_CARD};border:1px solid {BORDER};"
            f"border-radius:6px;color:{TEXT_MAIN};padding:4px;}}")


def _btn(primary: bool = False) -> str:
    if primary:
        return (f"QPushButton{{background:{ACCENT};color:#0A0C10;"
                f"border:none;border-radius:6px;padding:6px 14px;font-weight:bold;}}"
                f"QPushButton:hover{{background:{ACCENT}CC;}}")
    return (f"QPushButton{{background:transparent;color:{ACCENT};"
            f"border:1px solid {ACCENT};border-radius:6px;padding:6px 12px;}}")
