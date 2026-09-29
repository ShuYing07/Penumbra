# -*- coding: utf-8 -*-
"""组合优化页（模块四）：均值-方差 / 风险平价 / HRP + 优化结果 + 组合回测净值。"""
from __future__ import annotations

import traceback

import matplotlib
matplotlib.use("QtAgg")
import numpy as np
import pandas as pd
import pyqtgraph as pg
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PyQt6.QtCore import QThread, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (QComboBox, QGridLayout, QGroupBox, QHeaderView,
                             QLabel, QLineEdit, QPushButton, QTableWidget,
                             QTableWidgetItem, QVBoxLayout, QWidget)

from core.data.service import get_daily, market_of
from core.portfolio_optimizer import backtest_portfolio, optimize_portfolio

pg.setConfigOptions(antialias=True)

_METHODS = {"mv": "均值-方差（最大夏普）", "rp": "风险平价（等风险贡献）",
            "hrp": "层次风险平价（HRP）",
            "maxdiv": "最大分散化（Max Diversification）",
            "cvar": "分布鲁棒 CVaR（Worst-case 95%）"}

_THEME = {"bg": "#0A0C10", "fg": "#DCE1EB", "accent": "#00B4D8",
          "up": "#00C853", "down": "#FF1744", "grid": "#1E2530"}


def _canvas() -> FigureCanvasQTAgg:
    fig = Figure(figsize=(4.2, 2.9), dpi=96, facecolor=_THEME["bg"])
    ax = fig.add_subplot(111)
    ax.set_facecolor(_THEME["bg"])
    for sp in ax.spines.values():
        sp.set_color(_THEME["grid"])
    ax.tick_params(colors=_THEME["fg"], labelsize=8)
    ax.xaxis.label.set_color(_THEME["fg"])
    ax.yaxis.label.set_color(_THEME["fg"])
    ax.title.set_color(_THEME["fg"])
    return FigureCanvasQTAgg(fig)



class _OptWorker(QThread):
    done = pyqtSignal(object)
    bad = pyqtSignal(str)

    def __init__(self, tickers, method, max_w, rf):
        super().__init__()
        self.tickers, self.method, self.max_w, self.rf = tickers, method, max_w, rf

    def run(self) -> None:
        try:
            # 1) 拉取各标的日线 → 收益率矩阵（公共区间，不足降级）
            series, notes = {}, []
            for t in self.tickers:
                df, _ = get_daily(t)
                if df is None or len(df) < 30:
                    notes.append(f"{t}: 数据不足({0 if df is None else len(df)}根)")
                    continue
                close = df["close"].astype(float)
                if close.isna().all():
                    notes.append(f"{t}: 收盘价缺失")
                    continue
                series[t] = close
            if len(series) < 2:
                raise RuntimeError("可用标的不足 2 个：" + "；".join(notes))
            prices = pd.DataFrame(series)
            prices = prices.dropna(axis=0, how="all").ffill()
            rets = prices.pct_change().dropna(how="all").fillna(0.0)
            if rets.shape[0] < 30:
                raise RuntimeError(f"公共区间仅 {rets.shape[0]} 日，需 ≥30 日")

            # 2) 优化
            opt = optimize_portfolio(rets, method=self.method,
                                     max_weight=self.max_w,
                                     risk_free_rate=self.rf / 100.0)
            if not opt.get("ok"):
                raise RuntimeError(opt.get("note", "优化失败"))

            # 3) 组合回测
            bt = backtest_portfolio(prices, opt["weights"])
            self.done.emit({"opt": opt, "bt": bt, "rets": rets, "prices": prices,
                            "notes": notes})
        except Exception as e:  # noqa: BLE001
            self.bad.emit(f"{type(e).__name__}: {e}\n{traceback.format_exc(limit=3)}")


class PortfolioOptimizeTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker: _OptWorker | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        bar = QGridLayout()
        bar.addWidget(QLabel("标的(逗号分隔,≥2)"), 0, 0)
        self.ed_tickers = QLineEdit("SH600519, SZ300750, AAPL")
        bar.addWidget(self.ed_tickers, 0, 1, 1, 3)
        bar.addWidget(QLabel("优化方法"), 0, 4)
        self.cb_method = QComboBox()
        for k, v in _METHODS.items():
            self.cb_method.addItem(v, k)
        bar.addWidget(self.cb_method, 0, 5)

        bar.addWidget(QLabel("单只最大权重%"), 1, 0)
        self.ed_maxw = QLineEdit("40")
        bar.addWidget(self.ed_maxw, 1, 1)
        bar.addWidget(QLabel("无风险利率%"), 1, 2)
        self.ed_rf = QLineEdit("2")
        bar.addWidget(self.ed_rf, 1, 3)
        self.btn_run = QPushButton("开始优化")
        self.btn_run.clicked.connect(self.run_opt)
        bar.addWidget(self.btn_run, 1, 4, 1, 2)
        self.lbl_status = QLabel("优化结果与组合回测均为客观计算，不构成投资建议")
        self.lbl_status.setStyleSheet("color: gray;")
        bar.addWidget(self.lbl_status, 2, 0, 1, 6)

        # 指标卡
        sum_box = QGroupBox("优化结果")
        sg = QGridLayout(sum_box)
        self._sum: dict[str, QLabel] = {}
        for c, (key, name) in enumerate((
                ("engine", "引擎"), ("er", "预期年化%"), ("vol", "年化波动%"),
                ("sharpe", "夏普"), ("bt_total", "组合回测总收益%"),
                ("bt_dd", "组合回测最大回撤%"))):
            sg.addWidget(QLabel(name), 0, c * 2)
            lab = QLabel("—")
            sg.addWidget(lab, 0, c * 2 + 1)
            self._sum[key] = lab

        # 权重表
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["标的", "权重%", "风险贡献"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setMaximumHeight(200)

        # 净值曲线
        self.plot = pg.PlotWidget()
        self.plot.addLegend()
        self.plot.showGrid(x=True, y=True, alpha=0.3)
        self.plot.setLabel("left", "组合净值")
        self._curve: pg.PlotDataItem | None = None

        # 权重饼图（matplotlib，暗色主题）
        self.fig_pie = _canvas()
        self.fig_pie.setMinimumHeight(220)
        self.fig_frontier = _canvas()
        self.fig_frontier.setMinimumHeight(220)
        charts = QGridLayout()
        charts.addWidget(QLabel("优化后权重"), 0, 0)
        charts.addWidget(QLabel("有效前沿（随机采样组合可行域）"), 0, 1)
        charts.addWidget(self.fig_pie, 1, 0)
        charts.addWidget(self.fig_frontier, 1, 1)

        v = QVBoxLayout(self)
        v.addLayout(bar)
        v.addWidget(sum_box)
        v.addWidget(self.table)
        v.addLayout(charts)
        v.addWidget(self.plot, 1)

    def run_opt(self) -> None:
        if self._worker and self._worker.isRunning():
            return
        tickers = [t.strip().upper() for t in self.ed_tickers.text().split(",") if t.strip()]
        if len(tickers) < 2:
            self.lbl_status.setText("组合优化至少输入 2 个标的")
            return
        bad = [t for t in tickers if market_of(t) == "UNKNOWN"]
        if bad:
            self.lbl_status.setText(f"无法识别标的：{bad}")
            return
        try:
            max_w = min(max(float(self.ed_maxw.text() or 40), 5), 100) / 100.0
            rf = float(self.ed_rf.text() or 2)
        except ValueError:
            self.lbl_status.setText("最大权重/无风险利率应为数字")
            return
        self.btn_run.setEnabled(False)
        self.lbl_status.setText("优化中：拉取日线 → 收益率矩阵 → 优化 → 组合回测…")
        self._worker = _OptWorker(tickers, self.cb_method.currentData(), max_w, rf)
        self._worker.done.connect(self._on_done)
        self._worker.bad.connect(self._on_bad)
        self._worker.start()

    @pyqtSlot(str)
    def _on_bad(self, msg: str) -> None:
        self.btn_run.setEnabled(True)
        self.lbl_status.setText(f"优化失败：{msg.splitlines()[0]}")
        self.plot.clear()
        self.table.setRowCount(0)
        for fig in (self.fig_pie, self.fig_frontier):
            fig.figure.clear()
            fig.figure.add_subplot(111).set_facecolor(_THEME["bg"])
            fig.draw()

    @pyqtSlot(object)
    def _on_done(self, d) -> None:
        self.btn_run.setEnabled(True)
        opt, bt, notes = d["opt"], d["bt"], d["notes"]
        self.lbl_status.setText(
            f"完成：{opt['method']}（{opt['engine']}）"
            + (f"；跳过：{'、'.join(notes)}" if notes else ""))

        self._sum["engine"].setText(opt["engine"])
        self._sum["er"].setText(f"{opt['expected_return']}%")
        self._sum["vol"].setText(f"{opt['volatility']}%")
        self._sum["sharpe"].setText(str(opt["sharpe"]))
        if bt.get("ok"):
            self._sum["bt_total"].setText(f"{bt['total_return_pct']}%")
            self._sum["bt_dd"].setText(f"{bt['max_drawdown_pct']}%")
        else:
            self._sum["bt_total"].setText("—")
            self._sum["bt_dd"].setText("—")

        w = opt["weights"]
        rc = opt.get("risk_contrib") or []
        self.table.setRowCount(len(w))
        for r, (code, pct) in enumerate(w.items()):
            vals = [code, f"{pct}%",
                    f"{rc[r] * 100:.2f}%" if r < len(rc) else "—"]
            for c, val in enumerate(vals):
                item = QTableWidgetItem(val)
                if c == 1 and isinstance(pct, (int, float)):
                    item.setForeground(QColor("#00B4D8"))
                self.table.setItem(r, c, item)

        # 净值曲线
        self.plot.clear()
        if bt.get("ok") and bt.get("nav") is not None:
            nav = bt["nav"]
            x = list(range(len(nav)))
            self.plot.setTitle(f"组合净值 · 回测区间共 {bt['bars']} 个交易日")
            self.plot.plot(x, nav.tolist(), pen=pg.mkPen("#00B4D8", width=2),
                           name="优化组合")
            ax = self.plot.getAxis("bottom")
            step = max(1, len(x) // 8)
            ax.setTicks([[(i, str(nav.index[i])) for i in range(0, len(x), step)]])
        self._draw_charts(opt, d.get("rets"))

    # ---------- 模块四：权重饼图 + 有效前沿 ----------
    def _draw_charts(self, opt: dict, rets) -> None:
        """暗色主题权重饼图与随机采样组合可行域（有效前沿示意）。"""
        w = opt.get("weights") or {}
        codes = list(w.keys())
        pcts = [float(w[c]) for c in codes]
        self.fig_pie.figure.clear()
        ax = self.fig_pie.figure.add_subplot(111)
        ax.set_facecolor(_THEME["bg"])
        colors = ["#00B4D8", "#00C853", "#FFA726", "#9B59B6", "#F1C40F",
                  "#E74C3C", "#5DADE2", "#7DCEA0", "#F1948A", "#85929E"]
        ax.pie(pcts, labels=None, startangle=90, counterclock=False,
               colors=colors[:len(pcts)], wedgeprops={"edgecolor": _THEME["bg"],
                                                      "linewidth": 1.2})
        labels = [f"{c} {p:.1f}%" for c, p in zip(codes, pcts)]
        ax.legend(labels, loc="center left", bbox_to_anchor=(0.98, 0.5),
                  fontsize=7, facecolor=_THEME["bg"], edgecolor=_THEME["grid"],
                  labelcolor=_THEME["fg"])
        ax.set_title("优化后权重", fontsize=9, color=_THEME["fg"])
        self.fig_pie.figure.tight_layout()
        self.fig_pie.draw()

        # 有效前沿：随机采样 400 组权重（同等区间），展示可行域 + 最优解
        self.fig_frontier.figure.clear()
        ax2 = self.fig_frontier.figure.add_subplot(111)
        ax2.set_facecolor(_THEME["bg"])
        for sp in ax2.spines.values():
            sp.set_color(_THEME["grid"])
        ax2.tick_params(colors=_THEME["fg"], labelsize=8)
        ax2.xaxis.label.set_color(_THEME["fg"])
        ax2.yaxis.label.set_color(_THEME["fg"])
        ax2.title.set_color(_THEME["fg"])
        if rets is not None and len(rets.columns) == len(codes) and len(rets) >= 30:
            m = rets[codes].mean().to_numpy() * 252
            cov = rets[codes].cov().to_numpy() * 252
            n = len(codes)
            rng = np.random.default_rng(7)
            xf, yf = [], []
            for _ in range(400):
                v = rng.random(n)
                v = v / v.sum()
                xf.append(float(np.sqrt(v @ cov @ v)))
                yf.append(float(v @ m))
            ax2.scatter(xf, yf, s=6, color="#3A4658", alpha=0.65,
                        label="随机组合可行域")
            vol_opt = float(np.sqrt(np.array(w[pct] for pct in codes) @ cov
                                    @ np.array([w[pct] for pct in codes])))
            er_opt = float(np.array([w[pct] for pct in codes]) @ m)
            ax2.scatter([vol_opt], [er_opt], s=42, marker="*",
                        color=_THEME["accent"], zorder=5, label="当前最优解")
            ax2.legend(fontsize=7, facecolor=_THEME["bg"], edgecolor=_THEME["grid"],
                       labelcolor=_THEME["fg"])
            ax2.set_xlabel("年化波动", fontsize=8)
            ax2.set_ylabel("年化收益", fontsize=8)
            ax2.set_title("有效前沿（采样可行域）", fontsize=9, color=_THEME["fg"])
            ax2.grid(color=_THEME["grid"], alpha=0.4)
        else:
            ax2.text(0.5, 0.5, "收益率矩阵不可用，无法绘制前沿",
                     ha="center", va="center", transform=ax2.transAxes,
                     color=_THEME["fg"], fontsize=9)
        self.fig_frontier.figure.tight_layout()
        self.fig_frontier.draw()
