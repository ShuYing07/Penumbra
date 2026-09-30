# -*- coding: utf-8 -*-
"""回测页：选标的+规则策略→历史日线回放（t+1 开盘成交），指标/权益曲线/成交流水。"""
from __future__ import annotations

import json
from datetime import datetime

import pyqtgraph as pg
from PyQt6.QtCore import QThread, Qt, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (QComboBox, QDateEdit, QDoubleSpinBox, QGridLayout, QGroupBox,
                             QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton,
                             QSpinBox, QTableWidget, QTableWidgetItem, QTabWidget,
                             QVBoxLayout, QWidget)

from core.config import DATA_DIR, DISCLAIMER
from core.data.service import get_daily, market_of
from core.quant.backtest import (METRIC_LABELS, STRATEGY_META, BacktestConfig, run_backtest,
                                 strategy_choices)

pg.setConfigOptions(antialias=True)
BACKTEST_DIR = DATA_DIR / "backtests"


class _BacktestWorker(QThread):
    """后台跑回测（纯计算+可能联网补数据），避免卡 UI。"""

    done = pyqtSignal(object)
    bad = pyqtSignal(str)

    def __init__(self, ticker, strategy, params, capital, position, start, end):
        super().__init__()
        self.ticker, self.strategy, self.params = ticker, strategy, params
        self.capital, self.position = capital, position
        # 注意：不能用 self.start 命名，会遮蔽 QThread.start 方法
        self.start_date, self.end_date = start, end

    def run(self) -> None:
        try:
            from core.quant.backtest import BacktestConfig
            from core.quant.audit import run_audit
            df, status = get_daily(self.ticker)
            market = market_of(self.ticker)
            cfg = BacktestConfig(ticker=self.ticker, market=market,
                                 init_capital=self.capital, position_pct=self.position,
                                 start=self.start_date or None, end=self.end_date or None)
            res = run_backtest(df, market, self.strategy, self.params, cfg)
            # 严谨性审计（前视偏差 + Walk-Forward；失败不影响主回测结果）
            try:
                res._audit = run_audit(df, market, self.strategy, self.params, cfg)
            except Exception as e:  # noqa: BLE001
                res._audit = {"error": f"{type(e).__name__}: {e}"}
            # 留痕：结果落 data/backtests/
            BACKTEST_DIR.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            out = BACKTEST_DIR / f"{self.ticker}_{self.strategy}_{ts}.json"
            payload = {"ticker": self.ticker, "market": market, "strategy": self.strategy,
                       "params": res.params, "config": res.config_snapshot,
                       "metrics": res.metrics, "generated_at": ts,
                       "trades": res.trades.to_dict("records"),
                       "equity": res.equity.reset_index().to_dict("records")}
            out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            res._saved_to = str(out)
            res._data_status = status
            self.done.emit(res)
        except Exception as e:  # noqa: BLE001
            self.bad.emit(f"{type(e).__name__}: {e}")


class BacktestTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker: _BacktestWorker | None = None
        self._param_boxes: dict[str, QWidget] = {}
        self._build_ui()

    # ---------------- UI ----------------
    def _build_ui(self) -> None:
        # 控制条
        bar = QGridLayout()
        bar.addWidget(QLabel("标的"), 0, 0)
        self.ed_ticker = QLineEdit("SH600519")
        self.ed_ticker.setMaximumWidth(130)
        bar.addWidget(self.ed_ticker, 0, 1)

        bar.addWidget(QLabel("策略"), 0, 2)
        self.cb_strategy = QComboBox()
        for key, label in strategy_choices():
            self.cb_strategy.addItem(label, key)
        self.cb_strategy.currentIndexChanged.connect(self._on_strategy_changed)
        bar.addWidget(self.cb_strategy, 0, 3)

        bar.addWidget(QLabel("初始资金"), 0, 4)
        self.sp_capital = QDoubleSpinBox()
        self.sp_capital.setRange(10_000, 1e10)
        self.sp_capital.setValue(1_000_000)
        self.sp_capital.setMaximumWidth(120)
        bar.addWidget(self.sp_capital, 0, 5)

        bar.addWidget(QLabel("仓位%"), 0, 6)
        self.sp_position = QDoubleSpinBox()
        self.sp_position.setRange(10, 100)
        self.sp_position.setValue(100)
        self.sp_position.setMaximumWidth(70)
        bar.addWidget(self.sp_position, 0, 7)

        bar.addWidget(QLabel("起"), 1, 0)
        self.dt_start = QDateEdit()
        self.dt_start.setCalendarPopup(True)
        self.dt_start.setSpecialValueText("不限")
        self.dt_start.setMinimumDate(self.dt_start.minimumDate())
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

        self.btn_run = QPushButton("开始回测")
        self.btn_run.clicked.connect(self.run_backtest)
        bar.addWidget(self.btn_run, 1, 4, 1, 2)
        self.btn_factor = QPushButton("因子筛选")
        self.btn_factor.setToolTip("自动生成候选因子假设并统计验证（t检验）")
        self.btn_factor.clicked.connect(self._run_factor_screen)
        bar.addWidget(self.btn_factor, 1, 6)
        self.lbl_status = QLabel("信号 t 日收盘生成 → t+1 开盘成交（无前视），含佣金/印花税/滑点")
        bar.addWidget(self.lbl_status, 1, 6, 1, 3)

        # 策略参数区（按策略切换显示）
        params_row = QHBoxLayout()
        params_row.addWidget(self._build_rsi_box())
        params_row.addWidget(self._build_ma_box())
        params_row.addWidget(self._build_macd_box())
        self.lbl_bh_hint = QLabel("买入持有：首日开盘满仓买入并持有到期末，作为基准对照。")
        params_row.addWidget(self.lbl_bh_hint)
        params_row.addStretch(1)

        # 指标表
        self.metric_table = QTableWidget(len(METRIC_LABELS), 2)
        self.metric_table.setHorizontalHeaderLabels(["指标", "值"])
        self.metric_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.metric_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.metric_table.verticalHeader().setVisible(False)
        self.metric_table.setMaximumHeight(240)
        for r, (_key, label) in enumerate(METRIC_LABELS):
            self.metric_table.setItem(r, 0, QTableWidgetItem(label))
            self.metric_table.setItem(r, 1, QTableWidgetItem("—"))

        # 权益曲线
        self.curve = pg.PlotWidget(title="权益曲线：策略 vs 买入持有基准")
        self.curve.showGrid(x=True, y=True, alpha=0.25)
        self.curve.addLegend(offset=(8, 8))
        self.curve.setLabel("left", "权益（元）")
        self.curve.setMaximumHeight(220)

        # 成交流水表
        self.trade_table = QTableWidget(0, 9)
        self.trade_table.setHorizontalHeaderLabels(
            ["信号日", "成交日", "方向", "价格", "股数", "金额", "费用", "回合盈亏", "原因/持仓天数"])
        self.trade_table.horizontalHeader().setSectionResizeMode(8, QHeaderView.ResizeMode.Stretch)
        self.trade_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.trade_table.verticalHeader().setVisible(False)

        # 结果页签：回测结果 / 策略审计
        self.results_tabs = QTabWidget()
        page_res = QWidget()
        rv = QVBoxLayout(page_res)
        rv.setContentsMargins(0, 4, 0, 0)
        rv.addWidget(self.metric_table)
        rv.addWidget(self.curve)
        rv.addWidget(self.trade_table, 1)

        page_audit = QWidget()
        av = QVBoxLayout(page_audit)
        av.setContentsMargins(0, 4, 0, 0)
        self.audit_table = QTableWidget(0, 2)
        self.audit_table.setHorizontalHeaderLabels(["审计项", "结果"])
        self.audit_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.audit_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.audit_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.audit_table.verticalHeader().setVisible(False)
        self.audit_hint = QLabel(
            "策略审计：① 前视偏差扫描——在信号产生时刻截断未来数据重算信号，"
            "比对是否偏移（通过/可疑/未通过）；② Walk-Forward——样本内/样本外分段绩效，"
            "识别过拟合。运行回测后自动生成。")
        self.audit_hint.setWordWrap(True)
        self.audit_hint.setStyleSheet("color:#8b949e;padding:2px 0")
        av.addWidget(self.audit_hint)
        av.addWidget(self.audit_table, 1)
        self.results_tabs.addTab(page_res, "回测结果")
        self.results_tabs.addTab(page_audit, "策略审计")

        v = QVBoxLayout(self)
        v.addLayout(bar)
        v.addLayout(params_row)
        v.addWidget(self.results_tabs)
        v.addWidget(QLabel(DISCLAIMER))
        self._on_strategy_changed(0)

    def _param_group(self, key: str, title: str, fields) -> QGroupBox:
        box = QGroupBox(title)
        h = QHBoxLayout(box)
        edits = {}
        for name, label, default, kind in fields:
            h.addWidget(QLabel(label))
            if kind == "int":
                w = QSpinBox()
                w.setRange(1, 500)
                w.setValue(int(default))
            else:
                w = QDoubleSpinBox()
                w.setRange(1, 100)
                w.setValue(float(default))
            w.setMaximumWidth(70)
            h.addWidget(w)
            edits[name] = w
        self._param_edits = getattr(self, "_param_edits", {})
        self._param_edits[key] = edits
        self._param_boxes[key] = box
        return box

    def _build_rsi_box(self) -> QGroupBox:
        return self._param_group("rsi_reversion", "RSI 参数", [
            ("rsi_period", "周期", 14, "int"),
            ("buy_thr", "买入<", 30, "float"),
            ("sell_thr", "卖出>", 70, "float"),
        ])

    def _build_ma_box(self) -> QGroupBox:
        return self._param_group("ma_cross", "均线参数", [
            ("fast", "短均线", 5, "int"),
            ("slow", "长均线", 20, "int"),
        ])

    def _build_macd_box(self) -> QGroupBox:
        return self._param_group("macd_cross", "MACD 参数", [
            ("macd_fast", "快线", 12, "int"),
            ("macd_slow", "慢线", 26, "int"),
            ("macd_signal", "信号线", 9, "int"),
        ])

    def _on_strategy_changed(self, _idx: int) -> None:
        key = self.cb_strategy.currentData()
        for k, box in self._param_boxes.items():
            box.setVisible(k == key)
        self.lbl_bh_hint.setVisible(key == "buy_hold")

    # ---------------- 逻辑 ----------------
    def run_backtest(self) -> None:
        if self._worker and self._worker.isRunning():
            return
        ticker = self.ed_ticker.text().strip().upper()
        if not ticker:
            self.lbl_status.setText("请输入标的代码，如 SH600519 / AAPL / BTC-USD")
            return
        strategy = self.cb_strategy.currentData()
        params = {name: w.value() for name, w in
                  self._param_edits.get(strategy, {}).items()}
        start = None if self.dt_start.date() == self.dt_start.minimumDate() \
            else self.dt_start.date().toString("yyyy-MM-dd")
        end = None if self.dt_end.date() == self.dt_end.minimumDate() \
            else self.dt_end.date().toString("yyyy-MM-dd")

        self.btn_run.setEnabled(False)
        self.lbl_status.setText(f"回测运行中：{ticker} / {STRATEGY_META[strategy]['label']} …")
        self._worker = _BacktestWorker(ticker, strategy, params,
                                       self.sp_capital.value(), self.sp_position.value(),
                                       start, end)
        self._worker.done.connect(self._on_done)
        self._worker.bad.connect(self._on_bad)
        self._worker.start()

    @pyqtSlot(str)
    def _on_bad(self, msg: str) -> None:
        self.btn_run.setEnabled(True)
        self.lbl_status.setText(f"回测失败：{msg}")

    @pyqtSlot(object)
    def _on_done(self, res) -> None:
        self.btn_run.setEnabled(True)
        m = res.metrics
        self.lbl_status.setText(
            f"完成（数据 {getattr(res, '_data_status', '')}）：总收益 {m['total_return_pct']}% "
            f"vs 基准 {m['benchmark_return_pct']}%，最大回撤 {m['max_drawdown_pct']}%，"
            f"夏普 {m['sharpe']}，结果已存 {getattr(res, '_saved_to', '')}")

        # 指标表
        for r, (key, _label) in enumerate(METRIC_LABELS):
            self.metric_table.item(r, 1).setText(str(m.get(key)))

        # 权益曲线
        self.curve.clear()
        eq = res.equity
        if len(eq) >= 2:
            xs = list(range(len(eq)))
            self.curve.plot(xs, eq["strategy"].tolist(),
                            pen=pg.mkPen("#c0392b", width=2), name="策略")
            self.curve.plot(xs, eq["benchmark"].tolist(),
                            pen=pg.mkPen("#7f8c8d", width=1, style=Qt.PenStyle.DashLine),
                            name="买入持有基准")
            step = max(1, len(eq) // 8)
            ticks = [(i, str(eq.index[i])[2:]) for i in range(0, len(eq), step)]
            self.curve.getAxis("bottom").setTicks([ticks])
            self.curve.autoRange()

        # 成交流水
        trades = res.trades
        self.trade_table.setRowCount(len(trades))
        for r in range(len(trades)):
            t = trades.iloc[r]
            reason = str(t.get("reason", ""))
            if t.get("hold_days") is not None and str(t.get("hold_days")) != "nan":
                reason = f"{reason}｜持仓{int(t['hold_days'])}天"
            pnl = t.get("pnl")
            pnl_s = f"{float(pnl):+,.0f}" if pnl is not None and str(pnl) != "nan" else "—"
            vals = (t["signal_date"], t["fill_date"], t["side"], t["price"], t["shares"],
                    f"{float(t['amount']):,.0f}", f"{float(t['fee']):,.0f}", pnl_s, reason)
            for c, val in enumerate(vals):
                item = QTableWidgetItem(str(val))
                if c == 2:
                    item.setForeground(QColor("#c0392b" if val == "买入" else "#1e8449"))
                self.trade_table.setItem(r, c, item)

        # 策略审计
        self._fill_audit(getattr(res, "_audit", None))

    def _fill_audit(self, audit: dict | None) -> None:
        rows: list[tuple[str, str]] = []
        if not audit:
            rows.append(("策略审计", "未生成（可重跑回测）"))
        elif "error" in audit:
            rows.append(("审计失败", audit["error"]))
        else:
            la = audit.get("lookahead") or {}
            if la.get("verdict") == "na":
                rows.append(("前视偏差扫描", f"不适用：{la.get('reason', '')}"))
            elif la.get("verdict") == "error":
                rows.append(("前视偏差扫描", f"失败：{la.get('reason', '')}"))
            else:
                verdict_map = {"pass": "✅ 通过", "suspect": "⚠️ 可疑", "fail": "❌ 未通过"}
                rows.append(("前视偏差扫描",
                             f"{verdict_map.get(la.get('verdict'), la.get('verdict'))} "
                             f"（检查 {la.get('checked', 0)} 个信号点，偏移 {la.get('mismatches', 0)} 个）"))
                if la.get("detail"):
                    det = "; ".join(
                        f"{d['date']}: 全量={d['sig_full']}→截断={d['sig_trunc']}"
                        for d in la["detail"])
                    rows.append(("偏移明细", det))
            wf = audit.get("walk_forward") or {}
            if "error" in wf:
                rows.append(("Walk-Forward", wf["error"]))
            else:
                m_in, m_out, m_full = wf.get("in") or {}, wf.get("out") or {}, wf.get("full") or {}
                rows.append(("切分点", f"{wf.get('split_date', '')}（样本内 {wf.get('in_bars', 0)} 根 / "
                                       f"样本外 {wf.get('out_bars', 0)} 根）"))
                rows.append(("样本内收益", f"{m_in.get('total_return_pct', '—')}% "
                                        f"（回撤 {m_in.get('max_drawdown_pct', '—')}%，夏普 {m_in.get('sharpe', '—')}）"))
                rows.append(("样本外收益", f"{m_out.get('total_return_pct', '—')}% "
                                        f"（回撤 {m_out.get('max_drawdown_pct', '—')}%，夏普 {m_out.get('sharpe', '—')}）"))
                rows.append(("全样本收益", f"{m_full.get('total_return_pct', '—')}% "
                                        f"（回撤 {m_full.get('max_drawdown_pct', '—')}%，夏普 {m_full.get('sharpe', '—')}）"))
                rows.append(("过拟合提示",
                             "样本外收益显著低于样本内 → 警惕过拟合" if
                             (m_out.get('total_return_pct') is not None and
                              m_in.get('total_return_pct') is not None and
                              float(m_out['total_return_pct']) < float(m_in['total_return_pct']) * 0.5)
                             else "样本内外表现接近 → 稳健性较好"))
            rb = audit.get("robust") or {}
            if "error" in rb:
                rows.append(("稳健性指标", rb["error"]))
            elif rb:
                g = rb.get("gt_score") or {}
                rows.append(("GT-Score", f"{g.get('gt_score', '—')} / 100"
                            + (f"（绩效 {g.get('perf_term', 0):.0f} · 显著性 {g.get('significance_term', 0):.0f}"
                               f" · 一致性 {g.get('consistency_term', 0):.0f}"
                               f" · 下行惩罚 {g.get('downside_penalty', 0):.0f}）"
                               if g.get('gt_score') is not None else "")))
                rows.append(("Sharpe 稳定性",
                             f"{rb.get('sharpe_stability', '—')}（0~1，越接近1越稳定）"))
                ls = rb.get("long_short") or {}
                if ls.get("n_rounds"):
                    rows.append(("多空统计",
                                 f"{ls.get('n_rounds', 0)} 回合 · 胜率 {ls.get('win_rate_pct', 0)}% · "
                                 f"平均 {ls.get('avg_return_pct', 0)}% · "
                                 f"最大盈 {ls.get('max_win_pct', 0)}% / 最大亏 {ls.get('max_loss_pct', 0)}% · "
                                 f"极端 {ls.get('extreme_rounds', 0)} 次"))
                hd = rb.get("holding") or {}
                if hd.get("total_days"):
                    rows.append(("持仓统计（套牢/踏空）",
                                 f"持仓 {hd.get('position_days', 0)} 天 / 空仓 {hd.get('flat_days', 0)} 天 · "
                                 f"套牢(浮亏>{hd.get('trapped_threshold_pct', 5)}%) {hd.get('trapped_days', 0)} 天 "
                                 f"({hd.get('trapped_ratio_pct', 0)}%) · "
                                 f"踏空 {hd.get('missed_segments', 0)} 段"
                                 + (f"（基准累计涨 {hd.get('missed_bench_pct', 0)}%）"
                                    if hd.get('missed_bench_pct') else "")))
        self.audit_table.setRowCount(len(rows))
        for r, (k, v) in enumerate(rows):
            self.audit_table.setItem(r, 0, QTableWidgetItem(k))
            self.audit_table.setItem(r, 1, QTableWidgetItem(str(v)))

    def _run_factor_screen(self) -> None:
        """自动因子筛选：生成假设→统计验证→弹窗展示结果。"""
        from PyQt6.QtWidgets import QMessageBox
        ticker = self.ed_ticker.text().strip().upper()
        if not ticker:
            QMessageBox.warning(self, "提示", "请先输入标的代码")
            return
        try:
            from core.quant.factor_hypothesis import run_factor_screening
            df, _ = get_daily(ticker)
            if df is None or len(df) < 60:
                QMessageBox.warning(self, "提示", "数据不足（需≥60根日线）")
                return
            results = run_factor_screening(df)
            lines = [f"📊 因子筛选结果（{ticker}）\n"]
            for r in results:
                sig = "✅显著" if r.get("significant") else "❌不显著"
                lines.append(
                    f"【{r['description']}】{sig}\n"
                    f"  信号次数: {r.get('signals')}, "
                    f"平均收益: {r.get('mean_return_pct')}%, "
                    f"胜率: {r.get('win_rate_pct')}%, "
                    f"t值: {r.get('t_stat')}\n"
                    f"  逻辑: {r.get('logic')}\n")
            QMessageBox.information(self, "因子筛选完成", "\n".join(lines))
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "因子筛选失败", f"{type(e).__name__}: {e}")
