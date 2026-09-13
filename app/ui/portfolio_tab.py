# -*- coding: utf-8 -*-
"""组合回测页：多标的统一策略 + 权重漂移/定期再平衡，组合净值 vs buy_hold 基准。"""
from __future__ import annotations

import json

import pyqtgraph as pg
from PyQt6.QtCore import Qt, QThread, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (QComboBox, QGridLayout, QGroupBox, QHeaderView,
                             QLabel, QLineEdit, QPushButton, QTableWidget,
                             QTableWidgetItem, QVBoxLayout, QWidget)

from core.data.service import market_of
from core.portfolio.multi_backtest import REBALANCE_CHOICES, HoldingSpec, run_portfolio
from core.quant.backtest import STRATEGY_META

pg.setConfigOptions(antialias=True)

_REBAL_LABELS = {"none": "不再平衡(漂移)", "month": "月度再平衡",
                 "quarter": "季度再平衡", "year": "年度再平衡"}


class _PortfolioWorker(QThread):
    """后台逐标的回测+组合合成（可能联网补数据）。"""

    done = pyqtSignal(object)
    bad = pyqtSignal(str)

    def __init__(self, tickers, weights, strategy, params, rebalance, start, end):
        super().__init__()
        self.tickers, self.weights = tickers, weights
        self.strategy, self.params, self.rebalance = strategy, params, rebalance
        self.start, self.end = start, end

    def run(self) -> None:
        try:
            specs = [HoldingSpec(t, w) for t, w in zip(self.tickers, self.weights)]
            res = run_portfolio(specs, strategy=self.strategy, params=self.params,
                                rebalance=self.rebalance, start=self.start, end=self.end)
            self.done.emit(res)
        except Exception as e:  # noqa: BLE001
            self.bad.emit(f"{type(e).__name__}: {e}")


class PortfolioTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker: _PortfolioWorker | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        bar = QGridLayout()
        bar.addWidget(QLabel("标的(逗号分隔)"), 0, 0)
        self.ed_tickers = QLineEdit("SH600519, SH510300, 0700.HK")
        bar.addWidget(self.ed_tickers, 0, 1, 1, 3)
        bar.addWidget(QLabel("权重(可选)"), 0, 4)
        self.ed_weights = QLineEdit("")
        self.ed_weights.setPlaceholderText("留空等权，或 0.5,0.3,0.2")
        bar.addWidget(self.ed_weights, 0, 5)

        bar.addWidget(QLabel("策略"), 1, 0)
        self.cb_strategy = QComboBox()
        for key in ("buy_hold", "rsi_reversion", "ma_cross", "macd_cross"):
            self.cb_strategy.addItem(STRATEGY_META[key]["label"], key)
        bar.addWidget(self.cb_strategy, 1, 1)
        bar.addWidget(QLabel("再平衡"), 1, 2)
        self.cb_rebal = QComboBox()
        for k in REBALANCE_CHOICES:
            self.cb_rebal.addItem(_REBAL_LABELS[k], k)
        self.cb_rebal.setCurrentIndex(2)   # 默认季度
        bar.addWidget(self.cb_rebal, 1, 3)
        bar.addWidget(QLabel("策略参数JSON"), 1, 4)
        self.ed_params = QLineEdit("")
        self.ed_params.setPlaceholderText('可选，如 {"fast":5,"slow":20}')
        bar.addWidget(self.ed_params, 1, 5)

        self.btn_run = QPushButton("开始组合回测")
        self.btn_run.clicked.connect(self.run_backtest)
        bar.addWidget(self.btn_run, 2, 0, 1, 2)
        self.lbl_status = QLabel("公共区间自动取各标的交集；跨市场休市日按0收益；再平衡层费用v1不计")
        self.lbl_status.setStyleSheet("color: gray;")
        bar.addWidget(self.lbl_status, 2, 2, 1, 4)

        # 指标卡
        sum_box = QGroupBox("组合绩效（vs 同权重同再平衡 buy_hold 基准，超额=策略择时增益）")
        sg = QGridLayout(sum_box)
        self._sum: dict[str, QLabel] = {}
        for c, key in enumerate(("period", "total", "annual", "excess", "dd", "sharpe")):
            sg.addWidget(QLabel({"period": "公共区间", "total": "组合总收益",
                                 "annual": "组合年化", "excess": "超额收益",
                                 "dd": "最大回撤", "sharpe": "夏普"}[key]), 0, c * 2)
            lab = QLabel("—")
            sg.addWidget(lab, 0, c * 2 + 1)
            self._sum[key] = lab

        # 净值曲线
        self.plot = pg.PlotWidget()
        self.plot.addLegend()
        self.plot.showGrid(x=True, y=True, alpha=0.3)
        self.plot.setLabel("left", "净值(元)")
        self._curve_s = self._curve_b = None

        # 各标的贡献表
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["标的", "权重%", "年化%", "年化波动%", "最大回撤%", "夏普", "买入持有收益%"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setMaximumHeight(200)

        v = QVBoxLayout(self)
        v.addLayout(bar)
        v.addWidget(sum_box)
        v.addWidget(self.plot, 1)
        v.addWidget(self.table)

    def run_backtest(self) -> None:
        if self._worker and self._worker.isRunning():
            return
        tickers = [t.strip().upper() for t in self.ed_tickers.text().split(",") if t.strip()]
        if len(tickers) < 2:
            self.lbl_status.setText("组合回测至少输入 2 个标的（单标的请用回测页）")
            return
        bad = [t for t in tickers if market_of(t) == "UNKNOWN"]
        if bad:
            self.lbl_status.setText(f"无法识别标的：{bad}")
            return
        weights: list[float] = []
        wtxt = self.ed_weights.text().strip()
        if wtxt:
            try:
                weights = [float(x) for x in wtxt.split(",")]
            except ValueError:
                self.lbl_status.setText("权重应为逗号分隔数字")
                return
            if len(weights) != len(tickers):
                self.lbl_status.setText("权重数量与标的数量不一致")
                return
        params = None
        if self.ed_params.text().strip():
            try:
                params = json.loads(self.ed_params.text().strip())
            except json.JSONDecodeError:
                self.lbl_status.setText("策略参数 JSON 格式错误")
                return
        self.btn_run.setEnabled(False)
        self.lbl_status.setText("组合回测中：逐标的回测 + 净值合成…")
        self._worker = _PortfolioWorker(
            tickers, weights or [1.0] * len(tickers),
            self.cb_strategy.currentData(), params, self.cb_rebal.currentData(),
            None, None)
        self._worker.done.connect(self._on_done)
        self._worker.bad.connect(self._on_bad)
        self._worker.start()

    @pyqtSlot(str)
    def _on_bad(self, msg: str) -> None:
        self.btn_run.setEnabled(True)
        self.lbl_status.setText(f"组合回测失败：{msg}")

    @pyqtSlot(object)
    def _on_done(self, res) -> None:
        self.btn_run.setEnabled(True)
        m, bm = res.metrics, res.benchmark_metrics
        self.lbl_status.setText(
            f"完成：{res.start}~{res.end}，{m['bars']}交易日，"
            f"再平衡 {_REBAL_LABELS[res.rebalance]}")
        self._sum["period"].setText(f"{res.start}~{res.end}")
        self._sum["total"].setText(f"{m['total_return_pct']}%")
        self._sum["annual"].setText(f"{m['annual_return_pct']}%")
        el = self._sum["excess"]
        el.setText(f"{m['excess_return_pct']:+.2f}%")
        el.setStyleSheet("color: #c0392b;" if m["excess_return_pct"] >= 0 else "color: #1e8449;")
        self._sum["dd"].setText(f"{m['max_drawdown_pct']}%")
        self._sum["sharpe"].setText(str(m["sharpe"]))

        self.plot.clear()
        x = list(range(len(res.equity)))
        self.plot.setTitle(f"组合净值（基准 buy_hold 年化 {bm['annual_return_pct']}%，"
                           f"回撤 {bm['max_drawdown_pct']}%）")
        self.plot.plot(x, res.equity["strategy"].tolist(),
                       pen=pg.mkPen("#c0392b", width=2), name="策略组合")
        self.plot.plot(x, res.equity["benchmark"].tolist(),
                       pen=pg.mkPen("#7f8c8d", width=1, style=Qt.PenStyle.DashLine),
                       name="buy_hold基准")
        ax = self.plot.getAxis("bottom")
        step = max(1, len(x) // 8)
        ax.setTicks([[(i, str(res.equity.index[i])) for i in range(0, len(x), step)]])

        self.table.setRowCount(len(res.holdings))
        for r, h in enumerate(res.holdings):
            vals = [h["ticker"], h["weight_pct"], h["annual_return_pct"],
                    h["volatility_pct"], h["max_drawdown_pct"], h["sharpe"], h["buy_hold_pct"]]
            for c, val in enumerate(vals):
                item = QTableWidgetItem(str(val))
                if c in (2, 6) and isinstance(val, (int, float)):
                    item.setForeground(QColor("#c0392b" if val >= 0 else "#1e8449"))
                self.table.setItem(r, c, item)
