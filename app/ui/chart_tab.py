# -*- coding: utf-8 -*-
"""K线图页：pyqtgraph 蜡烛图 + MA5/10/20/60 + 布林带 + 成交量（日期轴取整索引映射）。"""
from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import QThread, pyqtSignal, pyqtSlot, Qt
from PyQt6.QtGui import QBrush, QColor, QPainter, QPen, QPicture
from PyQt6.QtWidgets import (QCheckBox, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                             QSpinBox, QVBoxLayout, QWidget)

from core.data import service
from core.quant import indicators as ind

pg.setConfigOptions(antialias=True)

GREEN = QColor(0, 170, 90)
RED = QColor(214, 64, 64)
MA_STYLES = ((5, "#f2c94c"), (10, "#56ccf2"), (20, "#bb6bd9"), (60, "#eb5757"))


class DateAxis(pg.AxisItem):
    """把整数索引刻度映射为日期字符串。"""

    def __init__(self, dates=None, **kw):
        super().__init__(**kw)
        self.dates = dates or []

    def tickStrings(self, values, scale, spacing):
        out = []
        for v in values:
            i = int(round(v))
            out.append(self.dates[i] if 0 <= i < len(self.dates) else "")
        return out


class CandlestickItem(pg.GraphicsObject):
    """简易蜡烛图（x 为整数索引，红涨绿跌配色反转按涨跌）。"""

    def __init__(self, data):
        super().__init__()
        self.data = data  # [(x, open, high, low, close)]
        self.picture: QPicture | None = None

    def _generate(self) -> None:
        self.picture = QPicture()
        p = QPainter(self.picture)
        w = 0.35
        for x, o, h, l, c in self.data:
            color = RED if c >= o else GREEN  # 国内习惯：涨红跌绿
            p.setPen(QPen(color))
            p.setBrush(QBrush(color))
            p.drawLine(pg.QtCore.QPointF(x, l), pg.QtCore.QPointF(x, h))
            p.drawRect(pg.QtCore.QRectF(x - w, min(o, c), w * 2, max(abs(c - o), 1e-9)))
        p.end()

    def boundingRect(self):  # noqa: N802
        if not self.data:
            return pg.QtCore.QRectF()
        xs = [d[0] for d in self.data]
        hi = max(d[2] for d in self.data)
        lo = min(d[3] for d in self.data)
        return pg.QtCore.QRectF(min(xs) - 1, lo, max(xs) - min(xs) + 2, hi - lo)

    def paint(self, p, *args) -> None:
        if self.picture is None:
            self._generate()
        self.picture.play(p)


class _Fetch(QThread):
    """后台取日线，避免 UI 卡顿。"""

    got = pyqtSignal(object, str)
    bad = pyqtSignal(str)

    def __init__(self, ticker: str, parent=None):
        super().__init__(parent)
        self.ticker = ticker

    def run(self) -> None:
        try:
            df, status = service.get_daily(self.ticker)
            self.got.emit(df, status)
        except Exception as e:  # noqa: BLE001
            self.bad.emit(f"{type(e).__name__}: {e}")


class ChartTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker: _Fetch | None = None
        self._bars = None
        self._status_txt = ""
        self._ticker = ""
        self._build_ui()

    def _build_ui(self) -> None:
        top = QHBoxLayout()
        top.addWidget(QLabel("标的："))
        self.ticker_input = QLineEdit()
        self.ticker_input.setPlaceholderText("600519 / AAPL / 0700.HK")
        self.ticker_input.setMaximumWidth(200)
        self.ticker_input.returnPressed.connect(self._on_load)
        top.addWidget(self.ticker_input)
        btn = QPushButton("加载")
        btn.clicked.connect(self._on_load)
        top.addWidget(btn)
        top.addWidget(QLabel("显示根数"))
        self.win_box = QSpinBox()
        self.win_box.setRange(60, 1200)
        self.win_box.setValue(250)
        self.win_box.valueChanged.connect(self._redraw)
        top.addWidget(self.win_box)
        self.boll_box = QCheckBox("布林带")
        self.boll_box.stateChanged.connect(self._redraw)
        top.addWidget(self.boll_box)
        top.addStretch()
        self.status = QLabel("")
        top.addWidget(self.status)

        self.price_axis = DateAxis(orientation="bottom")
        self.price = pg.PlotWidget(axisItems={"bottom": self.price_axis})
        self.price.setYRange(0, 1)
        self.price.getPlotItem().showAxis("bottom", False)
        self.price.showGrid(x=True, y=True, alpha=0.25)
        self.legend = self.price.addLegend(offset=(8, 8))
        # 十字光标
        self._vline = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen("#555", width=1))
        self._hline = pg.InfiniteLine(angle=0, movable=False, pen=pg.mkPen("#555", width=1))
        self.price.addItem(self._vline, ignoreBounds=True)
        self.price.addItem(self._hline, ignoreBounds=True)
        self._tooltip = pg.TextItem(anchor=(0, 1), color="#eee", fill=pg.mkBrush(0,0,0,180))
        self.price.addItem(self._tooltip, ignoreBounds=True)
        self.price.scene().sigMouseMoved.connect(self._on_mouse)
        self.vol_axis = DateAxis(orientation="bottom")
        self.vol = pg.PlotWidget(axisItems={"bottom": self.vol_axis})
        self.vol.getPlotItem().setXLink(self.price.getPlotItem())
        self.vol.showGrid(x=True, y=True, alpha=0.25)
        self.vol.setMaximumHeight(160)

        v = QVBoxLayout(self)
        v.addLayout(top)
        v.addWidget(self.price, 1)
        v.addWidget(self.vol, 0)

    def _on_mouse(self, pos):
        if not self.price.scene():
            return
        vb = self.price.getPlotItem().getViewBox()
        if not vb.sceneBoundingRect().contains(pos):
            self._tooltip.setVisible(False)
            self._vline.setVisible(False)
            self._hline.setVisible(False)
            return
        mousePoint = vb.mapSceneToView(pos)
        x = int(round(mousePoint.x()))
        y = mousePoint.y()
        self._vline.setPos(x)
        self._hline.setPos(y)
        self._vline.setVisible(True)
        self._hline.setVisible(True)
        self._tooltip.setText(f"x={x}, y={y:.2f}")
        self._tooltip.setPos(x, y)
        self._tooltip.setVisible(True)

    # ---------------- 逻辑 ----------------
    def load(self, ticker: str | None = None) -> None:
        if ticker:
            self.ticker_input.setText(ticker)
        t = self.ticker_input.text().strip().upper()
        if not t:
            self.status.setText("请输入标的代码")
            return
        if self._worker and self._worker.isRunning():
            return
        self._ticker = t
        self.status.setText(f"{t} 加载中…")
        self._worker = _Fetch(t)
        self._worker.got.connect(self._on_bars)
        self._worker.bad.connect(self._on_bad)
        self._worker.start()

    def _on_load(self) -> None:
        self.load()

    @pyqtSlot(object, str)
    def _on_bars(self, bars, status: str) -> None:
        self._bars = bars
        self._status_txt = status
        self._redraw()

    @pyqtSlot(str)
    def _on_bad(self, msg: str) -> None:
        self.status.setText(f"加载失败：{msg}")

    @pyqtSlot()
    def _redraw(self) -> None:
        bars = self._bars
        if bars is None or len(bars) == 0:
            return
        view = bars.tail(self.win_box.value())
        n = len(view)
        idx = np.arange(n)
        dates = [pd_ts.strftime("%y-%m-%d") for pd_ts in view.index]
        self.price_axis.dates = dates
        self.vol_axis.dates = dates

        o = view["open"].astype(float).values
        h = view["high"].astype(float).values
        l = view["low"].astype(float).values
        c = view["close"].astype(float).values

        self.price.clear()
        self.legend.clear()
        self.price.addItem(CandlestickItem(list(zip(idx, o, h, l, c))))
        close_full = bars["close"].astype(float)
        for n_, color in MA_STYLES:
            ma = ind.sma(close_full, n_).iloc[-n:]
            self.price.plot(idx, ma.values, pen=pg.mkPen(color, width=1.6), name=f"MA{n_}")
        if self.boll_box.isChecked():
            _, up, low = ind.boll(close_full)
            dash = pg.mkPen("#9aa0ff", width=1, style=Qt.PenStyle.DashLine)
            self.price.plot(idx, up.iloc[-n:].values, pen=dash)
            self.price.plot(idx, low.iloc[-n:].values, pen=dash)

        self.vol.clear()
        vol = view["volume"].astype(float).values
        brushes = [pg.mkBrush(RED if cc >= oo else GREEN) for oo, cc in zip(o, c)]
        self.vol.addItem(pg.BarGraphItem(x=idx, height=vol, width=0.7, brushes=brushes))

        self.status.setText(f"{self._ticker} · 共 {len(bars)} 根（显示 {n}）"
                            f"[{self._status_txt}] · 最新收盘 {c[-1]:.2f}")
        self.price.autoRange()
        self.vol.autoRange()
