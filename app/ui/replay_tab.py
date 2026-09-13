# -*- coding: utf-8 -*-
"""信号回放页：历史多点重跑 AI 管线 → t+5/10/20 日真实走势检验方向胜率。

与八期规则回测的区别：本页验证的是多智能体 AI 决策本身（mock 桩或真实 LLM）。
回放信号独立入 ai_replay_signals 表，不写真实 decisions/反思/模拟盘。
"""
from __future__ import annotations

from PyQt6.QtCore import QThread, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (QComboBox, QDateEdit, QGridLayout, QGroupBox, QHBoxLayout,
                             QHeaderView, QLabel, QLineEdit, QPushButton, QSpinBox,
                             QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from core.config import DISCLAIMER
from core.data.service import market_of
from core.replay import engine, store


class _ReplayWorker(QThread):
    """后台批量回放（每点跑完整 8 节点，可能联网），避免卡 UI。"""

    progress = pyqtSignal(int, int, str)
    done = pyqtSignal(str)
    bad = pyqtSignal(str)

    def __init__(self, ticker, start, end, step, engine_name):
        super().__init__()
        self.ticker, self.start, self.end = ticker, start, end
        self.step, self.engine_name = step, engine_name

    def run(self) -> None:
        try:
            bid = engine.run_replay(
                self.ticker, start=self.start, end=self.end,
                step_bars=self.step, engine=self.engine_name,
                progress_cb=lambda n, total, asof: self.progress.emit(n, total, asof))
            self.done.emit(bid)
        except Exception as e:  # noqa: BLE001
            self.bad.emit(f"{type(e).__name__}: {e}")


class ReplayTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker: _ReplayWorker | None = None
        self._build_ui()
        self._reload_batches()

    def _build_ui(self) -> None:
        bar = QGridLayout()
        bar.addWidget(QLabel("标的"), 0, 0)
        self.ed_ticker = QLineEdit("SH600519")
        self.ed_ticker.setMaximumWidth(130)
        bar.addWidget(self.ed_ticker, 0, 1)
        bar.addWidget(QLabel("引擎"), 0, 2)
        self.cb_engine = QComboBox()
        self.cb_engine.addItem("mock 离线规则桩(零成本)", "mock")
        self.cb_engine.addItem("deepseek 真实AI(计费)", "deepseek")
        self.cb_engine.addItem("local 本地模型", "local")
        bar.addWidget(self.cb_engine, 0, 3)
        bar.addWidget(QLabel("步长(交易日)"), 0, 4)
        self.sp_step = QSpinBox()
        self.sp_step.setRange(5, 120)
        self.sp_step.setValue(20)
        self.sp_step.setMaximumWidth(70)
        bar.addWidget(self.sp_step, 0, 5)

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
        self.btn_run = QPushButton("开始回放")
        self.btn_run.clicked.connect(self.run_replay)
        bar.addWidget(self.btn_run, 1, 4, 1, 2)

        self.lbl_status = QLabel("历史时点只凭当时数据决策（无前视）；默认 mock 为规则桩信号，非真实 AI 推理")
        self.lbl_status.setStyleSheet("color: gray;")

        # 汇总卡片
        summary_box = QGroupBox("批次汇总（方向胜率：买入后涨 / 卖出后跌；观望不计）")
        sg = QGridLayout(summary_box)
        self.lbl_sum_caption = QLabel("尚未回放")
        sg.addWidget(self.lbl_sum_caption, 0, 0, 1, 6)
        self._sum_labels: dict[tuple, QLabel] = {}
        headers = ["持有期", "已评估", "方向样本", "方向胜率", "平均收益", "多头均收", "空头均收"]
        for c, h in enumerate(headers):
            sg.addWidget(QLabel(h), 1, c)
        for r, h in ((2, 5), (3, 10), (4, 20)):
            sg.addWidget(QLabel(f"{h}日"), r, 0)
            for c in range(1, 7):
                lab = QLabel("—")
                sg.addWidget(lab, r, c)
                self._sum_labels[(h, c)] = lab

        # 历史批次
        hist = QHBoxLayout()
        hist.addWidget(QLabel("历史批次："))
        self.cb_batches = QComboBox()
        self.cb_batches.setMinimumWidth(420)
        hist.addWidget(self.cb_batches, 1)
        btn_view = QPushButton("查看")
        btn_view.clicked.connect(self._view_selected_batch)
        hist.addWidget(btn_view)

        # 明细表
        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels(
            ["时点", "引擎", "动作", "仓位%", "当时价", "5日收益", "10日收益",
             "20日收益", "命中10日"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)

        dis = QLabel(DISCLAIMER + "  局限：免费源无完整历史新闻/基本面，回放主要验证技术面→AI决策链路。")
        dis.setStyleSheet("color: gray;")

        v = QVBoxLayout(self)
        v.addLayout(bar)
        v.addWidget(self.lbl_status)
        v.addWidget(summary_box)
        v.addLayout(hist)
        v.addWidget(self.table, 1)
        v.addWidget(dis)

    def _date_str(self, w: QDateEdit) -> str | None:
        return None if w.date() == w.minimumDate() else w.date().toString("yyyy-MM-dd")

    def run_replay(self) -> None:
        if self._worker and self._worker.isRunning():
            return
        ticker = self.ed_ticker.text().strip().upper()
        if not ticker or market_of(ticker) == "UNKNOWN":
            self.lbl_status.setText("请输入有效标的，如 SH600519 / 0700.HK / SH510300")
            return
        self.btn_run.setEnabled(False)
        self.lbl_status.setText(f"回放运行中：{ticker}（每点跑 8 节点，请稍候）…")
        self._worker = _ReplayWorker(
            ticker, self._date_str(self.dt_start), self._date_str(self.dt_end),
            self.sp_step.value(), self.cb_engine.currentData())
        self._worker.progress.connect(self._on_progress)
        self._worker.done.connect(self._on_done)
        self._worker.bad.connect(self._on_bad)
        self._worker.start()

    @pyqtSlot(int, int, str)
    def _on_progress(self, n: int, total: int, asof: str) -> None:
        self.lbl_status.setText(f"回放进度 [{n}/{total}] 时点 {asof}")

    @pyqtSlot(str)
    def _on_bad(self, msg: str) -> None:
        self.btn_run.setEnabled(True)
        self.lbl_status.setText(f"回放失败：{msg}")

    @pyqtSlot(str)
    def _on_done(self, batch_id: str) -> None:
        self.btn_run.setEnabled(True)
        self.lbl_status.setText(f"回放完成：{batch_id}")
        self._reload_batches()
        self._show_batch(batch_id)

    def _reload_batches(self) -> None:
        self.cb_batches.clear()
        for b in store.batches():
            self.cb_batches.addItem(
                f"{b['batch_id']}  {b['ticker']}/{b['engine']}  {b['n']}点 "
                f"{b['start']}~{b['end']}  已评估{b['evaluated']}",
                b["batch_id"])

    def _view_selected_batch(self) -> None:
        bid = self.cb_batches.currentData()
        if bid:
            self._show_batch(bid)

    def _show_batch(self, batch_id: str) -> None:
        st = engine.batch_stats(batch_id)
        d = st["distribution"]
        self.lbl_sum_caption.setText(
            f"样本 {st['n']}：多 {d['多']} / 空 {d['空']} / 中性 {d['中性']} / 错误 {d['错误']}")
        for h, s in st["horizons"].items():
            vals = [s["evaluated"], s["directional"],
                    f"{s['win_rate_pct']}%" if s["win_rate_pct"] is not None else "—",
                    f"{s['avg_ret_pct']:+.2f}%" if s["avg_ret_pct"] is not None else "—",
                    f"{s['long_avg_pct']:+.2f}%" if s["long_avg_pct"] is not None else "—",
                    f"{s['short_avg_pct']:+.2f}%" if s["short_avg_pct"] is not None else "—"]
            for c, val in enumerate(vals, start=1):
                self._sum_labels[(h, c)].setText(str(val))

        rows = store.list_batch(batch_id)
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            if row["error"]:
                vals = [row["asof"], row["engine"], "错误", "—", "—", "—", "—", "—",
                        row["error"][:20]]
            else:
                def f(v):
                    return f"{v:+.2f}%" if v is not None else "—"
                vals = [row["asof"], row["engine"], row.get("action") or "—",
                        str(row.get("position_pct") if row.get("position_pct") is not None else "—"),
                        f"{row['price']:.4g}" if row.get("price") else "—",
                        f(row["ret_5"]), f(row["ret_10"]), f(row["ret_20"]),
                        {1: "✓ 命中", 0: "✗ 反向", None: "· 观望"}.get(row["hit_10"], "—")]
            for c, val in enumerate(vals):
                item = QTableWidgetItem(str(val))
                if c in (5, 6, 7) and val != "—":
                    item.setForeground(QColor("#c0392b" if float(str(val).rstrip("%")) >= 0
                                             else "#1e8449"))
                if c == 8:
                    if str(val).startswith("✓"):
                        item.setForeground(QColor("#c0392b"))
                    elif str(val).startswith("✗"):
                        item.setForeground(QColor("#1e8449"))
                if c == 2 and str(val) in ("买入", "强烈买入"):
                    item.setForeground(QColor("#c0392b"))
                elif c == 2 and str(val) in ("卖出", "回避"):
                    item.setForeground(QColor("#1e8449"))
                self.table.setItem(r, c, item)
