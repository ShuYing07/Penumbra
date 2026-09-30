# -*- coding: utf-8 -*-
"""金融专有组件（模块四 · 参考 Libra Design / Kepler Mobile）。

- TickerFlipLabel：数字翻牌动画——价格变化时滚动刷新（QPropertyAnimation
  对字号/位移做轻量滚动，离线可渲染）；
- HeavyWeightLabel：金额「承重墙」——关键金额用大字号、高对比突出；
- DepthChart：买卖档深度图（QPainter 轻量聚合条形图）；
- OrderBookPanel：五档订单簿（买卖档表格，红涨绿跌 A股惯例）；
- 全部组件颜色走 app.ui.ui_theme 的 up_color()/down_color()，语义统一。
"""
from __future__ import annotations

import logging

from PyQt6.QtCore import Qt, QPropertyAnimation, QRectF, QVariantAnimation, pyqtProperty
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel,
                             QTableWidget, QTableWidgetItem, QVBoxLayout,
                             QWidget)

try:
    from app.ui.ui_theme import DOWN_A_SHARE, UP_A_SHARE, down_color, up_color
except Exception:  # noqa: BLE001  # 独立运行/自检时回退 A股惯例默认色
    UP_A_SHARE = "#FF5252"
    DOWN_A_SHARE = "#26A69A"

    def up_color() -> str:
        return UP_A_SHARE

    def down_color() -> str:
        return DOWN_A_SHARE

log = logging.getLogger("stockai.ui.ticker")


def _chg_color(chg: float | None) -> str:
    """涨跌色（A股惯例：涨红跌绿）。"""
    if chg is None:
        return "#8B949E"
    return up_color() if chg >= 0 else down_color()


def _fmt(v, nd: int = 2) -> str:
    return f"{v:.{nd}f}" if v is not None else "—"


# ---------------------------------------------------------------------------
# 数字翻牌动画
# ---------------------------------------------------------------------------
class TickerFlipLabel(QLabel):
    """价格翻牌标签：setValue 时触发滚动动画（字号 0→峰值→回落）。"""

    def __init__(self, text: str = "—", parent=None):
        super().__init__(text, parent)
        self._zoom = 1.0
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(260)
        self._anim.valueChanged.connect(self._on_anim)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("color:#E6EDF3;font-weight:bold;")

    def _on_anim(self, v) -> None:
        self._zoom = float(v)
        f = self.font()
        f.setPointSizeF(f.pointSizeF() * (0.8 + 0.35 * self._zoom))
        self.setFont(f)

    def setValue(self, value: float | None, chg: float | None = None) -> None:
        self.setText(_fmt(value))
        if chg is not None:
            self.setStyleSheet(
                f"color:{_chg_color(chg)};font-weight:bold;font-size:20px;")
        else:
            self.setStyleSheet("color:#E6EDF3;font-weight:bold;font-size:20px;")
        self._anim.stop()
        self._anim.setStartValue(1.0)
        self._anim.setEndValue(0.0)
        self._anim.start()


class HeavyWeightLabel(QLabel):
    """金额承重墙：大字号 + 高对比 + 等宽数字，突出关键金额。"""

    def __init__(self, text: str = "—", parent=None):
        super().__init__(text, parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        f = QFont("Microsoft YaHei UI", 24)
        f.setBold(True)
        self.setFont(f)
        self.setStyleSheet("color:#E6EDF3;background:transparent;")

    def setAmount(self, value: float | None, chg: float | None = None) -> None:
        if value is None:
            self.setText("—")
            return
        self.setText(f"{value:,.2f}")
        self.setStyleSheet(
            f"color:{_chg_color(chg)};font-weight:bold;"
            f"font-size:24px;font-family:'JetBrains Mono',Consolas,monospace;")


# ---------------------------------------------------------------------------
# 深度图 / 订单簿
# ---------------------------------------------------------------------------
class DepthChart(QFrame):
    """买卖档聚合深度图（QPainter 轻量实现）。输入 {bids: [(price, size)], asks: [...]}。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(140)
        self._bids: list[tuple[float, float]] = []
        self._asks: list[tuple[float, float]] = []

    def set_data(self, bids: list[tuple[float, float]],
                 asks: list[tuple[float, float]]) -> None:
        self._bids = bids or []
        self._asks = asks or []
        self.update()

    def paintEvent(self, _ev) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), float(self.height())
        if not (self._bids or self._asks):
            p.setPen(QPen(QColor("#8B949E")))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "暂无深度数据")
            return
        mid = w / 2.0
        rows = self._bids + self._asks
        max_sz = max((s for _pr, s in rows), default=1.0) or 1.0
        n = max(len(self._bids), len(self._asks), 1)
        row_h = h / n
        # 买档：左侧（红）
        p.setPen(Qt.PenStyle.NoPen)
        for i, (pr, sz) in enumerate(self._bids):
            bw = (sz / max_sz) * (mid - 8)
            p.setBrush(QColor(UP_A_SHARE + "AA"))
            p.drawRect(QRectF(mid - bw, i * row_h + 1, bw, row_h - 3))
        # 卖档：右侧（绿）
        for i, (pr, sz) in enumerate(self._asks):
            bw = (sz / max_sz) * (mid - 8)
            p.setBrush(QColor(DOWN_A_SHARE + "AA"))
            p.drawRect(QRectF(mid, i * row_h + 1, bw, row_h - 3))
        p.setPen(QPen(QColor("#3F4145")))
        p.drawLine(int(mid), 0, int(mid), int(h))
        p.end()


class OrderBookPanel(QWidget):
    """五档订单簿：买五/卖五 + 量价（A股红涨绿跌）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.table = QTableWidget(10, 3)
        self.table.setHorizontalHeaderLabels(["档位", "价格", "数量"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        lay.addWidget(self.table)

    def set_data(self, bids: list[tuple[float, float]],
                 asks: list[tuple[float, float]]) -> None:
        """asks 从最接近现价向下（卖一→卖五），bids 从最接近现价向下（买一→买五）。"""
        self.table.setRowCount(len(asks) + len(bids))
        r = 0
        for i, (pr, sz) in enumerate(asks):  # 卖档：绿
            self._row(r, f"卖{i + 1}", pr, sz, DOWN_A_SHARE)
            r += 1
        for i, (pr, sz) in enumerate(bids):  # 买档：红
            self._row(r, f"买{i + 1}", pr, sz, UP_A_SHARE)
            r += 1

    def _row(self, r: int, label: str, pr: float, sz: float, color: str) -> None:
        for c, val in enumerate((label, f"{pr:.2f}", f"{sz:,.0f}")):
            it = QTableWidgetItem(val)
            if c == 1:
                it.setForeground(QColor(color))
            it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(r, c, it)


if __name__ == "__main__":
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))))
    # 自检：颜色与格式化纯逻辑
    assert _chg_color(1.5) == UP_A_SHARE
    assert _chg_color(-0.5) == DOWN_A_SHARE
    assert _fmt(3.14159) == "3.14"
    assert _fmt(None) == "—"
    print("ticker_components self-check ok")
