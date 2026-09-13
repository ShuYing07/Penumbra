# -*- coding: utf-8 -*-
"""模拟盘页：虚拟账户汇总、持仓明细、净值曲线、成交记录、决策胜率统计。"""
from __future__ import annotations

import pyqtgraph as pg
from PyQt6.QtCore import QThread, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import (QGridLayout, QHBoxLayout, QHeaderView, QLabel, QPushButton,
                             QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from core.data import service
from core.memory.reflection import decision_stats
from core.portfolio import paper

pg.setConfigOptions(antialias=True)


class _Refresh(QThread):
    """后台刷新：现价估值 → 账户/持仓/净值/成交/统计。"""

    got = pyqtSignal(dict, list, list, list, dict)
    bad = pyqtSignal(str)

    def run(self) -> None:
        try:
            prices: dict[str, float] = {}
            for pos in paper.positions():
                try:
                    q = service.get_realtime(pos["ticker"])
                    if q.get("price"):
                        prices[pos["ticker"]] = float(q["price"])
                except Exception:  # noqa: BLE001
                    continue  # 拿不到现价就沿用 last_price
            summary = paper.mark_to_market(prices) if prices else paper.summary()
            self.got.emit(summary, paper.positions(), paper.trades(50),
                          paper.equity_curve(), decision_stats())
        except Exception as e:  # noqa: BLE001
            self.bad.emit(f"{type(e).__name__}: {e}")


class PaperTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker: _Refresh | None = None
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        # ---- 账户汇总 ----
        grid = QGridLayout()
        self.lbl_cash = QLabel("现金 —")
        self.lbl_mv = QLabel("持仓市值 —")
        self.lbl_total = QLabel("总资产 —")
        self.lbl_pnl = QLabel("总盈亏 —")
        self.lbl_stats = QLabel("决策统计 —")
        for i, w in enumerate((self.lbl_cash, self.lbl_mv, self.lbl_total,
                               self.lbl_pnl, self.lbl_stats)):
            grid.addWidget(w, i // 3, i % 3)
        bar = QHBoxLayout()
        btn = QPushButton("刷新（拉现价估值）")
        btn.clicked.connect(self.refresh)
        btn_reset = QPushButton("清空重置")
        btn_reset.clicked.connect(self._reset)
        bar.addLayout(grid, 1)
        bar.addWidget(btn)
        bar.addWidget(btn_reset)

        # ---- 持仓表 ----
        self.pos_table = QTableWidget(0, 7)
        self.pos_table.setHorizontalHeaderLabels(
            ["标的", "市场", "股数", "成本价", "现价", "市值", "盈亏%"])
        self.pos_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch)
        self.pos_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.pos_table.verticalHeader().setVisible(False)
        self.pos_table.setMaximumHeight(180)

        # ---- 净值曲线 ----
        self.curve = pg.PlotWidget(title="模拟盘净值曲线")
        self.curve.showGrid(x=True, y=True, alpha=0.25)
        self.curve.addLegend(offset=(8, 8))
        self.curve.setLabel("left", "总资产（元）")
        self.curve.setMaximumHeight(200)

        # ---- 成交表 ----
        self.trade_table = QTableWidget(0, 8)
        self.trade_table.setHorizontalHeaderLabels(
            ["时间", "标的", "方向", "股数", "价格", "金额", "决策#", "备注"])
        self.trade_table.horizontalHeader().setSectionResizeMode(
            7, QHeaderView.ResizeMode.Stretch)
        self.trade_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.trade_table.verticalHeader().setVisible(False)

        v = QVBoxLayout(self)
        v.addLayout(bar)
        v.addWidget(self.pos_table)
        v.addWidget(self.curve)
        v.addWidget(self.trade_table, 1)

    # ---------------- 逻辑 ----------------
    def refresh(self) -> None:
        if self._worker and self._worker.isRunning():
            return
        self._worker = _Refresh()
        self._worker.got.connect(self._on_data)
        self._worker.bad.connect(self._on_bad)
        self._worker.start()

    def _reset(self) -> None:
        paper.reset()
        self.refresh()

    @pyqtSlot(str)
    def _on_bad(self, msg: str) -> None:
        self.lbl_stats.setText(f"刷新失败：{msg}")

    @pyqtSlot(dict, list, list, list, dict)
    def _on_data(self, summary, positions, trades, equity, stats) -> None:
        self.lbl_cash.setText(f"现金 {summary['cash']:,.0f}")
        self.lbl_mv.setText(f"持仓市值 {summary['market_value']:,.0f}")
        self.lbl_total.setText(f"总资产 {summary['total']:,.0f}")
        pnl = summary["pnl"]
        color = "#c0392b" if pnl >= 0 else "#1e8449"  # 涨红跌绿
        self.lbl_pnl.setText(f"总盈亏 {pnl:+,.0f}（{summary['pnl_pct']:+.2f}%）")
        self.lbl_pnl.setStyleSheet(f"color:{color}; font-weight:bold;")
        if stats.get("evaluated"):
            self.lbl_stats.setText(
                f"决策统计：共{stats['total']}条 已评估{stats['evaluated']}条 "
                f"方向正确率{stats['win_rate_pct']}% 平均实际收益{stats['avg_return_pct']}% "
                f"最佳{stats['best_pct']}% 最差{stats['worst_pct']}%")
        else:
            self.lbl_stats.setText(
                f"决策统计：共{stats['total']}条，暂无到期评估（决策满10个交易日后自动复盘）")

        # 持仓表
        self.pos_table.setRowCount(len(positions))
        for r, p in enumerate(positions):
            vals = (p["ticker"], p["market"], p["shares"], p["avg_cost"],
                    p["last_price"], f"{p['market_value']:,.0f}", f"{p['pnl_pct']:+.2f}%")
            for c, val in enumerate(vals):
                self.pos_table.setItem(r, c, QTableWidgetItem(str(val)))

        # 净值曲线
        self.curve.clear()
        if len(equity) >= 2:
            ys = [float(e["total"]) for e in equity]
            xs = list(range(len(ys)))
            color = "#c0392b" if ys[-1] >= ys[0] else "#1e8449"
            self.curve.plot(xs, ys, pen=pg.mkPen(color, width=2), name="总资产")
            step = max(1, len(equity) // 8)
            ticks = [(i, equity[i]["ts"][5:16]) for i in range(0, len(equity), step)]
            self.curve.getAxis("bottom").setTicks([ticks])
            self.curve.autoRange()

        # 成交表
        self.trade_table.setRowCount(len(trades))
        for r, t in enumerate(trades):
            vals = (str(t["ts"])[:19], t["ticker"], t["side"], t["shares"], t["price"],
                    f"{t['amount']:,.0f}", t["decision_id"] or "—", t["note"])
            for c, val in enumerate(vals):
                self.trade_table.setItem(r, c, QTableWidgetItem(str(val)))
