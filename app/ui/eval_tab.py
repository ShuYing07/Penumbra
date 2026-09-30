# -*- coding: utf-8 -*-
"""分析质量评测标签页（模块一）：八维雷达 + 历史趋势。

- 上方：输入 AI 输出文本 + 查询 + 参考数据（可选 JSON），点「评测」；
- 中部：八维评分条（0~1 进度条可视化）与总分/评级；
- 下方：历史评分趋势（最近 N 次总分折线，纯 QPainter 绘制，无新依赖）。
"""
from __future__ import annotations

import logging
import json

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import (QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
                             QProgressBar, QPushButton, QSplitter, QVBoxLayout,
                             QWidget)

from app.ui.ui_theme import (ACCENT, BG_CARD, BORDER, TEXT_MAIN, TEXT_SUB)

log = logging.getLogger("stockai.ui.eval")

_DIMS_CN = {"accuracy": "准确性", "citation": "引用", "clarity": "清晰度",
            "depth": "深度", "evidence": "有据可依", "timeliness": "时效性",
            "relevance": "相关性", "structure": "结构"}


class _TrendChart(QWidget):
    """历史总分趋势（QPainter 折线）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._points: list[float] = []
        self.setMinimumHeight(120)

    def set_data(self, totals: list[float]) -> None:
        self._points = totals
        self.update()

    def paintEvent(self, _ev) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor(BG_CARD))
        if not self._points:
            p.setPen(QColor(TEXT_SUB))
            p.drawText(QRectF(8, 8, w - 16, h - 16),
                       Qt.AlignmentFlag.AlignCenter, "暂无评测历史，先在上方评测一次")
            return
        pad = 10
        max_v, min_v = 1.0, 0.0
        for i, v in enumerate(self._points):
            x = pad + i * (w - 2 * pad) / max(1, len(self._points) - 1)
            y = h - pad - (v - min_v) / (max_v - min_v) * (h - 2 * pad)
            p.setPen(QPen(QColor(ACCENT), 2))
            if i > 0:
                p.drawLine(int(px), int(py), int(x), int(y))
            p.setBrush(QColor(ACCENT))
            p.drawEllipse(int(x) - 3, int(y) - 3, 6, 6)
            px, py = x, y
        p.setPen(QColor(TEXT_SUB))
        p.drawText(QRectF(pad, 2, w - 2 * pad, 18), Qt.AlignmentFlag.AlignLeft,
                   f"最近 {len(self._points)} 次评测总分趋势")


class EvalTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        title = QLabel("分析质量评测（FORCE-Bench 八维）")
        title.setStyleSheet(f"color:{TEXT_MAIN};font-size:16px;font-weight:bold;")
        root.addWidget(title)

        split = QSplitter(Qt.Orientation.Vertical)

        # ---- 输入区 ----
        inp = QWidget()
        il = QVBoxLayout(inp)
        il.addWidget(QLabel("AI 输出文本"))
        self.text = QPlainTextEdit()
        self.text.setPlaceholderText(
            "粘贴要评测的分析文本…（含数字、数据来源、结构标记得分更高）")
        self.text.setStyleSheet(_box_style())
        self.text.setMinimumHeight(90)
        il.addWidget(self.text)
        row = QHBoxLayout()
        row.addWidget(QLabel("查询"))
        self.query = QLineEdit()
        self.query.setPlaceholderText("如：分析茅台技术面")
        self.query.setStyleSheet(_box_style())
        row.addWidget(self.query, 3)
        row.addWidget(QLabel("参考数据(JSON)"))
        self.ref = QLineEdit()
        self.ref.setPlaceholderText('{"close":320.5,"rsi14":62.9}（可选）')
        self.ref.setStyleSheet(_box_style())
        row.addWidget(self.ref, 3)
        il.addLayout(row)
        b_run = QPushButton("▶ 评测")
        b_run.setStyleSheet(_btn(primary=True))
        b_run.clicked.connect(self._run)
        il.addWidget(b_run, 0, Qt.AlignmentFlag.AlignRight)
        split.addWidget(inp)

        # ---- 结果区 ----
        res = QWidget()
        rl = QVBoxLayout(res)
        self.total_lbl = QLabel("总分：—")
        self.total_lbl.setStyleSheet(
            f"color:{ACCENT};font-size:14px;font-weight:bold;")
        rl.addWidget(self.total_lbl)
        self.bars: dict[str, QProgressBar] = {}
        for key in ("accuracy", "citation", "clarity", "depth", "evidence",
                    "timeliness", "relevance", "structure"):
            h = QHBoxLayout()
            lbl = QLabel(_DIMS_CN[key])
            lbl.setStyleSheet(f"color:{TEXT_SUB};min-width:64px;")
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setTextVisible(True)
            bar.setStyleSheet(
                f"QProgressBar{{background:{BG_CARD};border:1px solid {BORDER};"
                f"border-radius:4px;height:16px;}}"
                f"QProgressBar::chunk{{background:{ACCENT};border-radius:4px;}}")
            h.addWidget(lbl)
            h.addWidget(bar, 1)
            rl.addLayout(h)
            self.bars[key] = bar
        rl.addWidget(QLabel("历史趋势"))
        self.trend = _TrendChart()
        rl.addWidget(self.trend, 1)
        split.addWidget(res)
        split.setSizes([240, 380])
        root.addWidget(split, 1)

        self._refresh_history()

    def _run(self) -> None:
        from core.eval.eval_benchmark import evaluate_analysis
        from core.eval.eval_suite import _record, STANDARD_CASES
        ref = {}
        if self.ref.text().strip():
            try:
                ref = json.loads(self.ref.text().strip())
            except Exception as e:  # noqa: BLE001
                self.total_lbl.setText(f"参考数据 JSON 解析失败：{e}")
                return
        r = evaluate_analysis(self.text.toPlainText(), self.query.text(), ref)
        scores, total = r["scores"], r["total"]
        self.total_lbl.setText(
            f"总分：{total:.2f}（{r['verdict']}） · 八维："
            f"{', '.join(f'{_DIMS_CN[k]}={v:.2f}' for k, v in scores.items())}")
        for k, bar in self.bars.items():
            bar.setValue(int(scores.get(k, 0) * 100))
        # 记录历史（用标准用例名或手动）
        try:
            _record({"case_id": "manual", "query": self.query.text(),
                     "total": total, "verdict": r["verdict"],
                     "scores": scores}, "manual")
        except Exception:  # noqa: BLE001
            pass
        self._refresh_history()

    def _refresh_history(self) -> None:
        from core.eval.eval_suite import history
        try:
            rows = history(limit=20)
        except Exception:  # noqa: BLE001
            rows = []
        totals = [float(r["total"]) for r in rows if r.get("total") is not None]
        self.trend.set_data(list(reversed(totals)))


def _box_style() -> str:
    return (f"QLineEdit,QPlainTextEdit{{background:{BG_CARD};"
            f"border:1px solid {BORDER};border-radius:6px;"
            f"color:{TEXT_MAIN};padding:4px;}}")


def _btn(primary: bool = False) -> str:
    if primary:
        return (f"QPushButton{{background:{ACCENT};color:#0A0C10;"
                f"border:none;border-radius:6px;padding:6px 14px;font-weight:bold;}}"
                f"QPushButton:hover{{background:{ACCENT}CC;}}")
    return (f"QPushButton{{background:transparent;color:{ACCENT};"
            f"border:1px solid {ACCENT};border-radius:6px;padding:6px 12px;}}"
            f"QPushButton:hover{{background:{ACCENT}22;}}")
