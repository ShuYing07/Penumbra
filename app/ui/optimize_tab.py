# -*- coding: utf-8 -*-
"""参数寻优页：网格批量回测 → 最优参数 + 绩效平原评级 + Walk-forward 跨期验证。

纪律提示写在页面上：网格寻优天然高估，孤立尖峰参数不可用，以平原评级与 OOS 分位为准。
"""
from __future__ import annotations

from PyQt6.QtCore import QThread, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (QComboBox, QDateEdit, QDoubleSpinBox, QGridLayout, QGroupBox,
                             QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton,
                             QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from core.data.service import get_daily, market_of
from core.optimize import grid as opt
from core.quant.backtest import STRATEGY_META


class _OptimizeWorker(QThread):
    """后台网格寻优（每组跑完整回测 + IS/OOS），避免卡 UI。"""

    progress = pyqtSignal(str)
    done = pyqtSignal(object)
    bad = pyqtSignal(str)

    def __init__(self, ticker, strategy, spec, objective, split, start, end):
        super().__init__()
        self.ticker, self.strategy, self.spec = ticker, strategy, spec
        self.objective, self.split = objective, split
        self.start, self.end = start, end

    def run(self) -> None:
        try:
            from core.quant.backtest import BacktestConfig

            df, _ = get_daily(self.ticker)
            market = market_of(self.ticker)
            cfg = BacktestConfig(ticker=self.ticker, market=market,
                                 start=self.start or None, end=self.end or None)
            out = opt.optimize(df, market, self.strategy, self.spec, cfg,
                               objective=self.objective, split=self.split,
                               progress_cb=lambda stage, i, t: self.progress.emit(
                                   f"{stage} {i}/{t}"))
            self.done.emit(out)
        except Exception as e:  # noqa: BLE001
            self.bad.emit(f"{type(e).__name__}: {e}")


class OptimizeTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker: _OptimizeWorker | None = None
        self._grid_boxes: dict[str, QLineEdit] = {}
        self._build_ui()
        self._rebuild_grid_boxes()

    def _build_ui(self) -> None:
        bar = QGridLayout()
        bar.addWidget(QLabel("标的"), 0, 0)
        self.ed_ticker = QLineEdit("SH510300")
        self.ed_ticker.setMaximumWidth(120)
        bar.addWidget(self.ed_ticker, 0, 1)
        bar.addWidget(QLabel("策略"), 0, 2)
        self.cb_strategy = QComboBox()
        for key in ("rsi_reversion", "ma_cross", "macd_cross"):
            self.cb_strategy.addItem(STRATEGY_META[key]["label"], key)
        self.cb_strategy.currentIndexChanged.connect(self._rebuild_grid_boxes)
        bar.addWidget(self.cb_strategy, 0, 3)
        bar.addWidget(QLabel("目标"), 0, 4)
        self.cb_obj = QComboBox()
        for k, label in opt.OBJECTIVE_LABELS.items():
            self.cb_obj.addItem(label, k)
        bar.addWidget(self.cb_obj, 0, 5)
        bar.addWidget(QLabel("IS比例"), 0, 6)
        self.sp_split = QDoubleSpinBox()
        self.sp_split.setRange(0.2, 0.8)
        self.sp_split.setSingleStep(0.1)
        self.sp_split.setValue(0.6)
        self.sp_split.setMaximumWidth(60)
        bar.addWidget(self.sp_split, 0, 7)

        bar.addWidget(QLabel("起"), 1, 0)
        self.dt_start = QDateEdit()
        self.dt_start.setCalendarPopup(True)
        self.dt_start.setSpecialValueText("不限")
        self.dt_start.setDate(self.dt_start.minimumDate())
        self.dt_start.setDisplayFormat("yyyy-MM-dd")
        bar.addWidget(self.dt_start, 1, 1)
        bar.addWidget(QLabel("止"), 1, 2)
        self.dt_end = QDateEdit()
        self.dt_end.setCalendarPopup(True)
        self.dt_end.setSpecialValueText("不限")
        self.dt_end.setDate(self.dt_end.minimumDate())
        self.dt_end.setDisplayFormat("yyyy-MM-dd")
        bar.addWidget(self.dt_end, 1, 3)
        self.btn_run = QPushButton("开始寻优")
        self.btn_run.clicked.connect(self.run_optimize)
        bar.addWidget(self.btn_run, 1, 4, 1, 2)

        # 网格编辑区（按策略动态重建）
        self.grid_box = QGroupBox("参数候选（逗号分隔；留空该行用默认网格该行）")
        self.grid_layout = QGridLayout(self.grid_box)
        bar.addWidget(self.grid_box, 2, 0, 1, 8)

        self.lbl_status = QLabel("网格 ≤500 组合；每组都是 t+1 成交的完整回测，含真实费率")
        self.lbl_status.setStyleSheet("color: gray;")

        # 结果区
        res_box = QGroupBox("寻优结论")
        rg = QGridLayout(res_box)
        self.lbl_best = QLabel("—")
        self.lbl_plateau = QLabel("—")
        self.lbl_wf = QLabel("—")
        for i, lab in enumerate((QLabel("最优参数："), self.lbl_best,
                                 QLabel("平原评估："), self.lbl_plateau,
                                 QLabel("Walk-forward："), self.lbl_wf)):
            rg.addWidget(lab, i // 2, (i % 2) * 3, 1, 3)
        self.lbl_plateau.setWordWrap(True)
        self.lbl_wf.setWordWrap(True)

        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(
            ["排名", "参数", "目标值", "年化%", "最大回撤%", "夏普", "胜率%", "交易笔数"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)

        warn = QLabel("⚠️ 网格+单区间寻优天然高估：孤立尖峰参数不可用于实盘；优先选平原且 OOS 分位≥0.6 的参数。")
        warn.setStyleSheet("color: #b9770e;")

        v = QVBoxLayout(self)
        v.addLayout(bar)
        v.addWidget(self.lbl_status)
        v.addWidget(res_box)
        v.addWidget(self.table, 1)
        v.addWidget(warn)

    def _rebuild_grid_boxes(self) -> None:
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._grid_boxes = {}
        strategy = self.cb_strategy.currentData()
        defaults = opt.DEFAULT_GRIDS[strategy]
        for c, (name, label, _dft) in enumerate(STRATEGY_META[strategy]["params"]):
            self.grid_layout.addWidget(QLabel(label), 0, c * 2)
            ed = QLineEdit(",".join(str(v) for v in defaults.get(name, [])))
            ed.setToolTip(f"{name} 候选值，逗号分隔")
            self.grid_layout.addWidget(ed, 0, c * 2 + 1)
            self._grid_boxes[name] = ed

    def _date_str(self, w: QDateEdit) -> str | None:
        return None if w.date() == w.minimumDate() else w.date().toString("yyyy-MM-dd")

    def _collect_spec(self) -> dict[str, list]:
        spec: dict[str, list] = {}
        for name, ed in self._grid_boxes.items():
            vals = []
            for tok in ed.text().split(","):
                tok = tok.strip()
                if tok:
                    vals.append(int(float(tok)))
            if vals:
                spec[name] = sorted(set(vals))
        return spec

    def run_optimize(self) -> None:
        if self._worker and self._worker.isRunning():
            return
        ticker = self.ed_ticker.text().strip().upper()
        if not ticker or market_of(ticker) == "UNKNOWN":
            self.lbl_status.setText("请输入有效标的，如 SH600519 / 0700.HK / SH510300")
            return
        spec = self._collect_spec()
        try:
            n = opt.expand_grid(spec)
            if len(n) > opt.MAX_COMBOS:
                self.lbl_status.setText(f"组合数 {len(n)} 超上限 {opt.MAX_COMBOS}，请缩小网格")
                return
        except ValueError as e:
            self.lbl_status.setText(f"网格无效：{e}")
            return
        self.btn_run.setEnabled(False)
        self.lbl_status.setText(f"寻优中：{len(n)} 个组合（含 IS/OOS 两遍）…")
        self._worker = _OptimizeWorker(
            ticker, self.cb_strategy.currentData(), spec,
            self.cb_obj.currentData(), self.sp_split.value(),
            self._date_str(self.dt_start), self._date_str(self.dt_end))
        self._worker.progress.connect(self._on_progress)
        self._worker.done.connect(self._on_done)
        self._worker.bad.connect(self._on_bad)
        self._worker.start()

    @pyqtSlot(str)
    def _on_progress(self, msg: str) -> None:
        self.lbl_status.setText(f"寻优中：{msg}")

    @pyqtSlot(str)
    def _on_bad(self, m: str) -> None:
        self.btn_run.setEnabled(True)
        self.lbl_status.setText(f"寻优失败：{m}")

    @pyqtSlot(object)
    def _on_done(self, out: dict) -> None:
        self.btn_run.setEnabled(True)
        self.lbl_status.setText(f"寻优完成：{out['n_combos']} 个组合")
        best, p, wf = out["best"], out["plateau"], out["walk_forward"]
        m = best["metrics"]
        self.lbl_best.setText(
            f"{best['params']}｜{out['objective_label']}={best['objective']}，"
            f"年化 {m['annual_return_pct']}%，回撤 {m['max_drawdown_pct']}%，夏普 {m['sharpe']}")
        pcolor = "#1e8449" if (p.get("robust") or 0) >= 0.7 else (
            "#b9770e" if (p.get("robust") or 0) >= 0.4 else "#c0392b")
        self.lbl_plateau.setText(p["rating"] + (f"（robust={p['robust']}）" if p.get("robust") is not None else ""))
        self.lbl_plateau.setStyleSheet(f"color: {pcolor};")
        wcolor = "#1e8449" if wf["oos_percentile"] >= 0.6 else (
            "#b9770e" if wf["oos_percentile"] >= 0.4 else "#c0392b")
        self.lbl_wf.setText(
            f"{wf['rating']}｜IS 选参 OOS 目标={wf['oos_objective_of_is_best']}，"
            f"OOS 分位={wf['oos_percentile']}（截止 {wf['split_date']}）")
        self.lbl_wf.setStyleSheet(f"color: {wcolor};")

        rows = out["results"][:15]
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            mm = row["metrics"]
            vals = [r + 1, str(row["params"]), row["objective"],
                    mm["annual_return_pct"], mm["max_drawdown_pct"], mm["sharpe"],
                    mm["win_rate_pct"], mm["trade_count"] if row["traded"] else "0(无交易)"]
            for c, val in enumerate(vals):
                item = QTableWidgetItem(str(val))
                if r == 0:
                    item.setForeground(QColor("#1e8449"))
                self.table.setItem(r, c, item)
