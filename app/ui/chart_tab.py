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
        # 绘图状态
        self._tool_mode: str | None = None
        self._pending: list[dict] = []
        self._drawing_items: list[tuple[list, int]] = []  # ([item], db_id)
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
        # 模块五：区间选择按钮（1M/3M/6M/1Y/MAX）
        for label, n in (("1M", 60), ("3M", 90), ("6M", 180), ("1Y", 250), ("MAX", 1200)):
            rb = QPushButton(label)
            rb.setCheckable(True)
            rb.setStyleSheet(
                "QPushButton{padding:3px 10px; border-radius:8px;}"
                "QPushButton:checked{background:rgba(0,229,255,0.15);color:#00E5FF;}")
            rb.clicked.connect(lambda _=False, _n=n, _b=rb: self._set_range(_n, _b))
            top.addWidget(rb)
        # 绘图工具栏（趋势线/水平线/斐波那契/矩形，参考 TradingView 简洁暗色）
        top.addWidget(QLabel("绘图"))
        self.tool_btns: dict[str, QPushButton] = {}
        for key, label in (("trend", "↗ 趋势线"), ("hlevel", "— 水平线"),
                           ("fib", "≋ 斐波那契"), ("rect", "▭ 矩形")):
            tb = QPushButton(label)
            tb.setCheckable(True)
            tb.setToolTip({"trend": "点击两点画趋势线", "hlevel": "点击一点画水平线",
                           "fib": "点击高/低两点画斐波那契回撤",
                           "rect": "点击对角两点画矩形区间"}[key])
            tb.setStyleSheet(
                "QPushButton{padding:3px 8px;border-radius:8px;font-size:12px;}"
                "QPushButton:checked{background:rgba(0,229,255,0.15);color:#00E5FF;}"
                "QPushButton:hover{border:1px solid rgba(0,229,255,0.4);}")
            tb.clicked.connect(lambda _=False, k=key: self._toggle_tool(k))
            top.addWidget(tb)
            self.tool_btns[key] = tb
        btn_undo = QPushButton("↶ 撤销")
        btn_undo.setToolTip("删除最后一条标注")
        btn_undo.clicked.connect(self._undo_drawing)
        top.addWidget(btn_undo)
        btn_clr = QPushButton("清空标注")
        btn_clr.clicked.connect(self._clear_drawings)
        top.addWidget(btn_clr)
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
        self.price.scene().sigMouseClicked.connect(self._on_click)
        self.vol_axis = DateAxis(orientation="bottom")
        self.vol = pg.PlotWidget(axisItems={"bottom": self.vol_axis})
        self.vol.getPlotItem().setXLink(self.price.getPlotItem())
        self.vol.showGrid(x=True, y=True, alpha=0.25)
        self.vol.setMaximumHeight(160)

        v = QVBoxLayout(self)
        v.addLayout(top)
        v.addWidget(self.price, 1)
        v.addWidget(self.vol, 0)

    def _set_range(self, n: int, btn=None) -> None:
        """区间按钮：设置显示根数并重绘（同一时刻仅一个区间高亮）。"""
        for b in self.findChildren(QPushButton):
            if b.text() in ("1M", "3M", "6M", "1Y", "MAX"):
                b.setChecked(False)
        if btn is not None:
            btn.setChecked(True)
        self.win_box.setValue(n)

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
        # 模块五：悬停图例 —— 显示该根 K 线的 OHLC / 成交量 / 均线值
        text = f"x={x}, y={y:.2f}"
        bars = self._bars
        if bars is not None and len(bars) > 0:
            view = bars.tail(self.win_box.value())
            if 0 <= x < len(view):
                try:
                    row = view.iloc[x]
                    o, h, l, c = (float(row["open"]), float(row["high"]),
                                  float(row["low"]), float(row["close"]))
                    vol = float(row.get("volume", 0))
                    text = (f"<b>OHLC</b> 开 {o:.2f} / 高 {h:.2f} / 低 {l:.2f} / 收 {c:.2f}<br/>"
                            f"量 {vol:,.0f}　")
                    close_full = bars["close"].astype(float)
                    for n_, _color in MA_STYLES:
                        ma = ind.sma(close_full, n_).iloc[x + max(len(bars) - len(view), 0)]
                        if ma == ma:  # 过滤 NaN
                            text += f"MA{n_} {ma:.2f}　"
                except Exception:  # noqa: BLE001
                    pass
        self._tooltip.setText(text)
        self._tooltip.setPos(x, y)
        self._tooltip.setVisible(True)

    # ---------------- 绘图标注（趋势线/水平线/斐波那契/矩形） ----------------
    def _toggle_tool(self, key: str) -> None:
        """切换绘图工具（互斥选择）。"""
        if self._tool_mode == key:
            self._tool_mode = None
            self._pending = []
            self.tool_btns[key].setChecked(False)
            self.status.setText("绘图已退出")
            return
        self._tool_mode = key
        self._pending = []
        for k, b in self.tool_btns.items():
            b.setChecked(k == key)
        self.status.setText(
            {"trend": "趋势线：点击图上第 1 点", "hlevel": "水平线：点击图上 1 点",
             "fib": "斐波那契：点击高点，再点击低点",
             "rect": "矩形：点击左上角，再点击右下角"}[key])

    def _on_click(self, event) -> None:
        if not self._tool_mode or self._bars is None or len(self._bars) == 0:
            return
        vb = self.price.getPlotItem().getViewBox()
        mousePoint = vb.mapSceneToView(event.scenePos())
        x = int(round(mousePoint.x()))
        view = self._bars.tail(self.win_box.value())
        offset = len(self._bars) - len(view)
        if not (0 <= x < len(view)):
            self.status.setText("请在图表区域内点击")
            return
        y = round(float(mousePoint.y()), 2)
        self._pending.append({"x": offset + x, "y": y})
        need = {"trend": 2, "hlevel": 1, "fib": 2, "rect": 2}[self._tool_mode]
        if len(self._pending) >= need:
            self._finish_drawing()

    def _finish_drawing(self) -> None:
        mode = self._tool_mode
        pts = list(self._pending)
        self._pending = []
        if mode == "hlevel":
            data, meta = [{"x": pts[0]["x"], "y": pts[0]["y"]}], {}
        elif mode == "trend":
            data, meta = [{"x": pts[0]["x"], "y": pts[0]["y"]},
                          {"x": pts[1]["x"], "y": pts[1]["y"]}], {}
        elif mode == "fib":
            a, b = (pts[0], pts[1]) if pts[0]["y"] >= pts[1]["y"] else (pts[1], pts[0])
            data = [{"x": a["x"], "y": a["y"]}, {"x": b["x"], "y": b["y"]}]
            meta = {"levels": [0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0]}
        else:  # rect
            data = [{"x": pts[0]["x"], "y": pts[0]["y"]},
                    {"x": pts[1]["x"], "y": pts[1]["y"]}]
            meta = {}
        from core.drawings import save_drawing
        db_id = save_drawing(self._ticker, mode, data, meta)
        items = self._render_drawing(mode, data, meta)
        self._drawing_items.append((items, db_id))
        for it in items:
            self.price.addItem(it, ignoreBounds=True)
        self.status.setText(f"已保存「{mode}」标注（点击撤销可删除）")
        self._toggle_tool(mode)  # 完成后自动退出工具模式

    def _render_drawing(self, mode: str, data: list[dict], meta: dict) -> list:
        """把全局索引坐标渲染为当前窗口内的绘图 item（越界整条跳过）。"""
        if self._bars is None:
            return []
        view = self._bars.tail(self.win_box.value())
        offset = len(self._bars) - len(view)
        n = len(view)

        def lx(gx: int) -> int:
            return gx - offset

        items: list = []
        pen = pg.mkPen("#00E5FF", width=1.4)
        if mode == "hlevel":
            x0, y0 = lx(data[0]["x"]), data[0]["y"]
            if not (0 <= x0 < n):
                return []
            line = pg.InfiniteLine(angle=0, pos=y0, pen=pen)
            lbl = pg.TextItem(f"{y0:.2f}", anchor=(0, 1), color="#00E5FF")
            lbl.setPos(x0, y0)
            items += [line, lbl]
        elif mode == "trend":
            (x1, y1), (x2, y2) = (lx(data[0]["x"]), data[0]["y"]), (lx(data[1]["x"]), data[1]["y"])
            if not (0 <= x1 < n and 0 <= x2 < n) or x1 == x2:
                return []
            import math
            angle = math.degrees(math.atan2(y2 - y1, x2 - x1))
            line = pg.InfiniteLine(pos=(x1, y1), angle=angle, pen=pen)
            items.append(line)
        elif mode == "fib":
            a, b = data[0], data[1]
            xa, xb = lx(a["x"]), lx(b["x"])
            if not (0 <= xa < n and 0 <= xb < n):
                return []
            levels = meta.get("levels") or [0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0]
            hi, lo = max(a["y"], b["y"]), min(a["y"], b["y"])
            for lv in levels:
                y = lo + (hi - lo) * lv
                ln = pg.InfiniteLine(angle=0, pos=y,
                                     pen=pg.mkPen("#bb6bd9", width=1,
                                                  style=Qt.PenStyle.DashLine))
                lbl = pg.TextItem(f"{lv:.1%} {y:.2f}", anchor=(0, 1),
                                  color="#bb6bd9", fill=pg.mkBrush(0, 0, 0, 160))
                lbl.setPos(xb, y)
                items += [ln, lbl]
        elif mode == "rect":
            (x1, y1), (x2, y2) = (lx(data[0]["x"]), data[0]["y"]), (lx(data[1]["x"]), data[1]["y"])
            if not (0 <= x1 < n and 0 <= x2 < n):
                return []
            roi = pg.RectROI(pos=(min(x1, x2), min(y1, y2)),
                             size=(abs(x2 - x1), abs(y2 - y1)),
                             pen=pg.mkPen("#FFA726", width=1.4))
            items.append(roi)
        return items

    def _restore_drawings(self) -> None:
        """重绘所有已存标注（_redraw 的 clear() 后调用）。"""
        # 先移除上一轮的渲染条目（可能已被 clear() 移除，忽略失败）
        for items, _db in self._drawing_items:
            for it in items:
                try:
                    self.price.removeItem(it)
                except Exception:  # noqa: BLE001
                    pass
        self._drawing_items = []
        from core.drawings import list_drawings
        if not self._ticker:
            return
        drawings = list_drawings(self._ticker)
        for d in drawings:
            items = self._render_drawing(d["type"], d["points"], d.get("meta") or {})
            if items:
                self._drawing_items.append((items, d["id"]))
                for it in items:
                    self.price.addItem(it, ignoreBounds=True)
    def _undo_drawing(self) -> None:
        if not self._drawing_items:
            self.status.setText("没有可撤销的标注")
            return
        items, db_id = self._drawing_items.pop()
        for it in items:
            try:
                self.price.removeItem(it)
            except Exception:  # noqa: BLE001
                pass
        from core.drawings import delete_drawing
        if db_id:
            delete_drawing(db_id)
        self.status.setText("已撤销最后一条标注")

    def _clear_drawings(self) -> None:
        from core.drawings import clear_ticker
        cleared = clear_ticker(self._ticker) if self._ticker else 0
        for items, _db in self._drawing_items:
            for it in items:
                try:
                    self.price.removeItem(it)
                except Exception:  # noqa: BLE001
                    pass
        self._drawing_items = []
        self.status.setText(f"已清空 {cleared} 条标注")

    # ---------------- 逻辑 ----------------
    def load(self, ticker: str | None = None) -> None:
        if ticker:
            self.ticker_input.setText(ticker)
        t = self.ticker_input.text().strip().upper()
        if not t:
            self.status.setText("请输入标的代码")
            return
        if self._worker and self._worker.isRunning():
            # 旧请求仍在途：明确提示而不是静默丢弃，避免"点了没反应"
            self.status.setText(f"上一请求仍在加载，请稍候再试（当前标的：{self._ticker}）")
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
        self._redraw()  # 末尾已恢复十字光标与绘图标注

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
        # clear() 会移除十字光标/悬停框，需重新挂载（修复重绘后光标丢失）
        for it in (self._vline, self._hline, self._tooltip):
            if it.scene() is None:
                self.price.addItem(it, ignoreBounds=True)
        self._restore_drawings()
