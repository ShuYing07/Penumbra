# -*- coding: utf-8 -*-
"""事件图谱标签页（模块四）：实体-事件-风险三层传导链可视化。

- 输入实体代码 + 若干文本（新闻/公告标题），点「建图」；
- QGraphicsView 简易力导向布局（弹簧+斥力迭代，50 节点内稳定）；
- 节点按层着色：实体=青、事件=紫、风险=橙；边标注关系；
- 右侧显示传导路径与因果推理（风险冲击评分）。
"""
from __future__ import annotations

import logging
import math

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import (QGraphicsEllipseItem, QGraphicsItem,
                             QGraphicsLineItem, QGraphicsScene,
                             QGraphicsTextItem, QGraphicsView, QHBoxLayout,
                             QLabel, QLineEdit, QPlainTextEdit, QPushButton,
                             QSplitter, QVBoxLayout, QWidget)

from app.ui.ui_theme import ACCENT, BG_CARD, BORDER, TEXT_MAIN, TEXT_SUB

log = logging.getLogger("stockai.ui.event_graph")

_LAYER_COLOR = {"entity": "#00E5FF", "event": "#BB6BD9", "risk": "#FFA726"}


class GraphCanvas(QGraphicsView):
    """简易力导向画布。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setBackgroundBrush(QColor(BG_CARD))
        self._items: list = []

    def clear_graph(self) -> None:
        for it in self._items:
            self._scene.removeItem(it)
        self._items = []

    def draw_graph(self, nodes: list, edges: list) -> None:
        self.clear_graph()
        if not nodes:
            return
        W, H = 860.0, 460.0
        pos = {n["id"]: QPointF(
            W * (0.15 + 0.7 * (hash(n["id"]) % 97) / 97.0),
            H * (0.15 + 0.7 * (hash(n["id"]) % 53) / 53.0))
            for n in nodes}
        # 简易力导向迭代
        for _ in range(40):
            forces = {nid: QPointF(0, 0) for nid in pos}
            for a in nodes:
                for b in nodes:
                    if a["id"] >= b["id"]:
                        continue
                    dx = pos[a["id"]].x() - pos[b["id"]].x()
                    dy = pos[a["id"]].y() - pos[b["id"]].y()
                    d = max(math.hypot(dx, dy), 20.0)
                    f = 900.0 / (d * d) * 6
                    forces[a["id"]] += QPointF(dx / d * f, dy / d * f)
                    forces[b["id"]] -= QPointF(dx / d * f, dy / d * f)
            # 弹簧（沿边）
            for e in edges:
                a, b = e["src"], e["dst"]
                if a not in pos or b not in pos:
                    continue
                dx = pos[b].x() - pos[a].x()
                dy = pos[b].y() - pos[a].y()
                d = max(math.hypot(dx, dy), 1.0)
                f = (d - 150.0) * 0.02
                forces[a] += QPointF(dx / d * f, dy / d * f)
                forces[b] -= QPointF(dx / d * f, dy / d * f)
            for nid, f in forces.items():
                pos[nid] += f * 0.12
                pos[nid].setX(min(W - 30, max(30, pos[nid].x())))
                pos[nid].setY(min(H - 30, max(30, pos[nid].y())))
        # 画边
        for e in edges:
            if e["src"] not in pos or e["dst"] not in pos:
                continue
            line = QGraphicsLineItem(
                QPointF(pos[e["src"]].x(), pos[e["src"]].y()),
                QPointF(pos[e["dst"]].x(), pos[e["dst"]].y()))
            line.setPen(QPen(QColor("#2A3340"), 1.2))
            self._scene.addItem(line)
            self._items.append(line)
        # 画节点
        for n in nodes:
            p = pos[n["id"]]
            color = _LAYER_COLOR.get(n.get("layer"), ACCENT)
            el = QGraphicsEllipseItem(QRectF(p.x() - 7, p.y() - 7, 14, 14))
            el.setBrush(QColor(color))
            el.setPen(QPen(QColor("#0A0C10"), 1))
            el.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
            self._scene.addItem(el)
            self._items.append(el)
            lbl = QGraphicsTextItem(n.get("label", n["id"])[:10])
            lbl.setDefaultTextColor(QColor(TEXT_MAIN))
            f = lbl.font()
            f.setPointSize(8)
            lbl.setFont(f)
            lbl.setPos(p.x() - 14, p.y() - 26)
            self._scene.addItem(lbl)
            self._items.append(lbl)
        self._scene.setSceneRect(0, 0, W, H)
        self.fitInView(0, 0, W, H, Qt.AspectRatioMode.KeepAspectRatio)


class EventGraphTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        title = QLabel("金融事件演化图谱（实体-事件-风险三层）")
        title.setStyleSheet(f"color:{TEXT_MAIN};font-size:16px;font-weight:bold;")
        root.addWidget(title)

        split = QSplitter(Qt.Orientation.Horizontal)

        left = QWidget()
        ll = QVBoxLayout(left)
        ll.addWidget(QLabel("实体（股票代码/公司）"))
        self.entity = QLineEdit("600519")
        self.entity.setStyleSheet(_box())
        ll.addWidget(self.entity)
        ll.addWidget(QLabel("新闻/公告文本（每行一条）"))
        self.texts = QPlainTextEdit()
        self.texts.setPlaceholderText(
            "贵州茅台业绩预增，净利润同比增长15%\n某股东减持套现1亿元\n"
            "公司收到政府补贴3000万元")
        self.texts.setStyleSheet(_box())
        ll.addWidget(self.texts, 1)
        b = QPushButton("▶ 建图并推理")
        b.setStyleSheet(_btn(primary=True))
        b.clicked.connect(self._run)
        ll.addWidget(b, 0, Qt.AlignmentFlag.AlignRight)
        split.addWidget(left)

        right = QWidget()
        rl = QVBoxLayout(right)
        self.canvas = GraphCanvas()
        rl.addWidget(self.canvas, 3)
        self.summary = QLabel("传导路径与风险推理将显示于此")
        self.summary.setWordWrap(True)
        self.summary.setStyleSheet(
            f"color:{TEXT_SUB};background:{BG_CARD};border:1px solid {BORDER};"
            f"border-radius:6px;padding:8px;")
        self.summary.setMinimumHeight(64)
        rl.addWidget(self.summary)
        split.addWidget(right)
        split.setSizes([340, 560])
        root.addWidget(split, 1)

    def _run(self) -> None:
        from core.event_graph import build_from_texts, query_event_chain, predict_impact
        entity = self.entity.text().strip() or "600519"
        texts = [t.strip() for t in self.texts.toPlainText().splitlines() if t.strip()]
        build_from_texts(entity, texts, industry="白酒")
        chain = query_event_chain(entity, depth=3)
        self.canvas.draw_graph(chain["nodes"], chain["edges"])
        imp = predict_impact(entity, texts, "白酒")
        path_str = " → ".join(p[0] for p in imp["path"][:8]) or "（无）"
        risks = "，".join(f"{k} {v:+.2f}" for k, v in
                          sorted(imp["risk_scores"].items(),
                                 key=lambda kv: -abs(kv[1]))[:5])
        self.summary.setText(
            f"传导路径：{path_str}\n风险推理：{imp['summary']}"
            + (f"　|　{risks}" if risks else ""))


def _box() -> str:
    return (f"QLineEdit,QPlainTextEdit{{background:{BG_CARD};"
            f"border:1px solid {BORDER};border-radius:6px;"
            f"color:{TEXT_MAIN};padding:4px;}}")


def _btn(primary: bool = False) -> str:
    if primary:
        return (f"QPushButton{{background:{ACCENT};color:#0A0C10;"
                f"border:none;border-radius:6px;padding:6px 14px;font-weight:bold;}}"
                f"QPushButton:hover{{background:{ACCENT}CC;}}")
    return (f"QPushButton{{background:transparent;color:{ACCENT};"
            f"border:1px solid {ACCENT};border-radius:6px;padding:6px 12px;}}")
