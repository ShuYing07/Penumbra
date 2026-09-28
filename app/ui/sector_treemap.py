# -*- coding: utf-8 -*-
"""板块热力图（Treemap）：按市值排列、按当日涨跌幅着色。

参考 OpenTerminal / Finviz 的 sector heatmap：
- 矩形面积 ≈ 板块成交额/市值权重，颜色表示涨跌幅（国内习惯：红涨绿跌）；
- 鼠标悬停显示板块名与涨跌幅；
- 数据优先 AKShare 板块行情，失败自动降级为演示数据（UI 永不空白）。
"""
from __future__ import annotations

import logging
import math

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QFont
from PyQt6.QtWidgets import QWidget

log = logging.getLogger("stockai.ui.sector_treemap")


def _demo_sectors() -> list[dict]:
    """演示数据（网络不可用时的兜底，保证 UI 不空白）。"""
    base = [("白酒", 4.2), ("半导体", 2.8), ("新能源", -1.6), ("医药", 0.8),
            ("银行", 0.3), ("地产", -2.4), ("券商", 1.1), ("军工", -0.5),
            ("AI算力", 5.6), ("消费电子", 1.9), ("光伏", -0.9), ("汽车", 0.6)]
    return [{"name": n, "chg": c, "amount": round(1200 - i * 40)} for i, (n, c) in enumerate(base)]


def _fetch_sectors() -> list[dict]:
    """AKShare 板块行情（失败返回空，由调用方降级）。"""
    try:
        import akshare as ak
        df = ak.stock_board_industry_name_em()
        if df is None or len(df) == 0:
            return []
        out = []
        for _, r in df.head(24).iterrows():
            try:
                out.append({"name": str(r.get("板块名称", "")),
                            "chg": float(r.get("涨跌幅", 0) or 0),
                            "amount": float(r.get("成交额", 0) or 0)})
            except Exception:  # noqa: BLE001
                continue
        return out
    except Exception as e:  # noqa: BLE001
        log.debug("板块数据不可用，使用演示数据: %s", e)
        return []


class SectorTreemap(QWidget):
    """自绘矩形树图。"""

    hovered = pyqtSignal(str)  # "板块名 +x.xx%"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(200)
        self._items: list[dict] = []
        self._rects: list[tuple[dict, QColor, QRectF-like]] = []
        self._hover: dict | None = None
        self.setMouseTracking(True)
        self.refresh()

    def refresh(self) -> None:
        items = _fetch_sectors() or _demo_sectors()
        self._items = items
        self._layout()
        self.update()

    # ---------- 布局：简单 squarified 矩形树图 ----------
    def _layout(self) -> None:
        w, h = max(self.width(), 1), max(self.height(), 1)
        total = sum(max(it["amount"], 1) for it in self._items)
        self._rects = []
        # 按成交额降序
        ordered = sorted(self._items, key=lambda x: -x["amount"])
        x, y = 0.0, 0.0
        rw, rh = float(w), float(h)
        row_h = 0.0
        for it in ordered:
            area = max(it["amount"], 1) / total * w * h
            need = area / max(rw, 1)
            if y + row_h + need > h and x + rw < w:  # 换行
                x += rw
                y = 0.0
                rw = float(w - x)
                rh = float(h)
                row_h = 0.0
            if row_h == 0:
                row_h = need
            self._rects.append((it, QColor("#2A3346"), (x, y, rw, need)))
            y += need
            rh -= need
            row_h = max(row_h, need)
        # 归一化（浮点误差兜底）
        self._rects = [(it, QColor("#2A3346"), tuple(r)) for it, _, r in self._rects]

    # ---------- 绘制 ----------
    def paintEvent(self, e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor("#0D1117"))
        for it, _base, (rx, ry, rw, rh) in self._rects:
            chg = it.get("chg", 0)
            # 国内习惯：红涨绿跌，饱和度随 |chg|
            if chg >= 0:
                col = QColor(214, 64, 64).lighter(100 - min(int(abs(chg) * 8), 60))
            else:
                col = QColor(0, 170, 90).lighter(100 - min(int(abs(chg) * 8), 60))
            rect = self._rect().adjusted(0, 0, -1, -1)
            # 用归一化后的绝对坐标
            R = (rx, ry, rw, rh)
            p.setBrush(col)
            p.setPen(QColor(13, 17, 23))
            p.drawRoundedRect(int(rx), int(ry), int(rw), int(rh), 3, 3)
            if rw > 40 and rh > 22:
                p.setPen(QColor(255, 255, 255))
                f = QFont(self.font())
                f.setPointSize(8)
                p.setFont(f)
                p.drawText(int(rx) + 4, int(ry) + 14, it["name"])
                p.drawText(int(rx) + 4, int(ry) + 28, f"{chg:+.2f}%")
        p.end()

    def _rect(self):
        from PyQt6.QtCore import QRect
        return QRect(0, 0, self.width(), self.height())

    # ---------- 悬停 ----------
    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        x, y = e.position().x(), e.position().y()
        self._hover = None
        for it, _c, (rx, ry, rw, rh) in self._rects:
            if rx <= x <= rx + rw and ry <= y <= ry + rh:
                self._hover = it
                self.hovered.emit(f"{it['name']}  {it.get('chg', 0):+.2f}%")
                break
        self.update()

    def leaveEvent(self, e) -> None:  # noqa: N802
        self._hover = None
        self.update()
        super().leaveEvent(e)
