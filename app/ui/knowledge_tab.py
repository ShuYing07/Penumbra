# -*- coding: utf-8 -*-
"""学习库页：语义检索（报告/新闻/反思）+ 相似历史形态检索 + 一键入库。"""
from __future__ import annotations

from PyQt6.QtCore import QThread, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import (QComboBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                             QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
                             QWidget)

from core.data import service
from core.memory import patterns as pat_mod
from core.memory import rag
from core.training import distill

_KINDS = [("全部", None), ("报告", "report"), ("新闻", "news"), ("反思", "reflection")]
_STRETCH = QHeaderView.ResizeMode.Stretch
_NO_EDIT = QTableWidget.EditTrigger.NoEditTriggers


class _RagWorker(QThread):
    op: str = ""
    got = pyqtSignal(list, dict)   # 检索结果 or 空列表, stats
    bad = pyqtSignal(str)

    def __init__(self, op: str, query: str = "", kind=None, parent=None):
        super().__init__(parent)
        self.op, self.query, self.kind = op, query, kind

    def run(self) -> None:
        try:
            if self.op == "index":
                n = (rag.index_reports() + rag.index_news() + rag.index_reflections())
                self.got.emit([{"info": f"入库完成，新增 {n} 条"}], rag.stats())
            else:
                self.got.emit(rag.search(self.query, kind=self.kind, n=10), rag.stats())
        except Exception as e:  # noqa: BLE001
            self.bad.emit(f"{type(e).__name__}: {e}")


class _PatWorker(QThread):
    got = pyqtSignal(list, dict, str)  # matches, agg, ticker
    bad = pyqtSignal(str)

    def __init__(self, ticker: str, parent=None):
        super().__init__(parent)
        self.ticker = ticker

    def run(self) -> None:
        try:
            bars, status = service.get_daily(self.ticker)
            matches, agg = pat_mod.find_similar(bars)
            self.got.emit(matches, agg or {}, f"{self.ticker}（{len(bars)}根 [{status}]）")
        except Exception as e:  # noqa: BLE001
            self.bad.emit(f"{type(e).__name__}: {e}")


class KnowledgeTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._rag_worker: _RagWorker | None = None
        self._pat_worker: _PatWorker | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        # ---- 语义检索 ----
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("语义检索："))
        self.query = QLineEdit()
        self.query.setPlaceholderText("如：白酒板块风险 / 美联储降息 / 止损纪律 …")
        self.query.returnPressed.connect(self._do_search)
        row1.addWidget(self.query, 1)
        self.kind_box = QComboBox()
        for label, _ in _KINDS:
            self.kind_box.addItem(label)
        row1.addWidget(self.kind_box)
        btn = QPushButton("搜索")
        btn.clicked.connect(self._do_search)
        row1.addWidget(btn)
        self.btn_index = QPushButton("一键入库（报告/新闻/反思）")
        self.btn_index.clicked.connect(self._do_index)
        row1.addWidget(self.btn_index)

        self.rag_table = QTableWidget(0, 5)
        self.rag_table.setHorizontalHeaderLabels(
            ["相关度", "类型", "日期", "标的", "内容"])
        self.rag_table.horizontalHeader().setSectionResizeMode(4, _STRETCH)
        self.rag_table.setEditTriggers(_NO_EDIT)
        self.rag_table.verticalHeader().setVisible(False)

        # ---- 形态检索 ----
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("形态检索："))
        self.ticker = QLineEdit()
        self.ticker.setPlaceholderText("SH600519 / AAPL / BTC-USD")
        self.ticker.setMaximumWidth(220)
        self.ticker.returnPressed.connect(self._do_pattern)
        row2.addWidget(self.ticker)
        btn2 = QPushButton("找相似历史形态")
        btn2.clicked.connect(self._do_pattern)
        row2.addWidget(btn2)
        row2.addStretch()
        self.pat_status = QLabel("")

        self.pat_table = QTableWidget(0, 6)
        self.pat_table.setHorizontalHeaderLabels(
            ["起始日", "结束日", "相似度", "后10日涨跌", "期间最大回撤", "期间最大上涨"])
        self.pat_table.setEditTriggers(_NO_EDIT)
        self.pat_table.verticalHeader().setVisible(False)
        self.pat_table.setMaximumHeight(200)

        self.lbl_stats = QLabel("学习库：空")

        # ---- 自学习蒸馏语料 ----
        row3 = QHBoxLayout()
        row3.addWidget(QLabel("蒸馏语料："))
        self.lbl_distill = QLabel("—")
        row3.addWidget(self.lbl_distill, 1)
        self.btn_export_distill = QPushButton("导出训练集(LLaMA-Factory)")
        self.btn_export_distill.setToolTip(
            "把云端教师推理(SFT)和决策对错标签(偏好)导出，供未来 LoRA/DPO 微调本地模型")
        self.btn_export_distill.clicked.connect(self._export_distill)
        row3.addWidget(self.btn_export_distill)

        v = QVBoxLayout(self)
        v.addLayout(row1)
        v.addWidget(self.rag_table, 1)
        v.addLayout(row2)
        v.addWidget(self.pat_status)
        v.addWidget(self.pat_table)
        v.addWidget(self.lbl_stats)
        v.addLayout(row3)
        self._refresh_distill_stats()

    def _refresh_distill_stats(self) -> None:
        try:
            s = distill.stats()
            by_s, by_l = s["sft_by_source"], s["pref_by_label"]
            self.lbl_distill.setText(
                f"SFT {s['sft_total']} 条（教师 {by_s.get('teacher', 0)} / "
                f"学生 {by_s.get('student', 0)}）｜ 决策偏好 {s['pref_total']} 条"
                f"（正确 {by_l.get('good', 0)} / 错误 {by_l.get('bad', 0)}"
                f" / 观望 {by_l.get('neutral', 0)}）")
        except Exception as e:  # noqa: BLE001
            self.lbl_distill.setText(f"统计失败：{e}")

    def _export_distill(self) -> None:
        try:
            r = distill.export_llamafactory()
            self.lbl_distill.setText(
                f"已导出：SFT {r['sft_rows']} 条 / 偏好 {r['preference_rows']} 条 → {r['sft']}")
        except Exception as e:  # noqa: BLE001
            self.lbl_distill.setText(f"导出失败：{type(e).__name__}: {e}")

    # ---------------- 动作 ----------------
    def _do_search(self) -> None:
        if self._rag_worker and self._rag_worker.isRunning():
            return
        kind = _KINDS[self.kind_box.currentIndex()][1]
        self._rag_worker = _RagWorker("search", self.query.text().strip(), kind)
        self._rag_worker.got.connect(self._on_search)
        self._rag_worker.bad.connect(self._on_bad)
        self._rag_worker.start()

    def _do_index(self) -> None:
        if self._rag_worker and self._rag_worker.isRunning():
            return
        self.btn_index.setEnabled(False)
        self.lbl_stats.setText("入库中…（首次约几秒）")
        self._rag_worker = _RagWorker("index")
        self._rag_worker.got.connect(self._on_search)
        self._rag_worker.bad.connect(self._on_bad)
        self._rag_worker.start()

    def _do_pattern(self) -> None:
        t = self.ticker.text().strip().upper()
        if not t or (self._pat_worker and self._pat_worker.isRunning()):
            return
        self.pat_status.setText(f"{t} 检索中…")
        self._pat_worker = _PatWorker(t)
        self._pat_worker.got.connect(self._on_pattern)
        self._pat_worker.bad.connect(self._on_bad)
        self._pat_worker.start()

    # ---------------- 槽 ----------------
    @pyqtSlot(str)
    def _on_bad(self, msg: str) -> None:
        self.lbl_stats.setText(f"失败：{msg}")
        self.btn_index.setEnabled(True)

    @pyqtSlot(list, dict)
    def _on_search(self, results, stats) -> None:
        self.btn_index.setEnabled(True)
        by = stats.get("by_kind", {})
        self.lbl_stats.setText(
            f"学习库：共 {stats.get('total', 0)} 条"
            f"（报告 {by.get('report', 0)} / 新闻 {by.get('news', 0)}"
            f" / 反思 {by.get('reflection', 0)}）")
        infos = [r for r in results if r.get("info")]
        if infos:
            self.rag_table.setRowCount(0)
            return
        self.rag_table.setRowCount(len(results))
        kind_cn = {"report": "报告", "news": "新闻", "reflection": "反思"}
        for r_, item in enumerate(results):
            meta = item.get("meta", {})
            snippet = (item.get("doc") or "")[:120].replace("\n", " ")
            vals = (f"{item.get('score', 0):.0%}", kind_cn.get(meta.get("kind"), meta.get("kind")),
                    meta.get("date"), meta.get("ticker") or "—", snippet)
            for c, val in enumerate(vals):
                self.rag_table.setItem(r_, c, QTableWidgetItem(str(val)))

    @pyqtSlot(list, dict, str)
    def _on_pattern(self, matches, agg, info) -> None:
        self.pat_status.setText(
            f"{info} ｜ 命中 {len(matches)} 段，后10日均值 "
            f"{agg.get('avg_forward_ret_pct', 0):+.2f}%，上涨占比 {agg.get('up_ratio_pct', 0):.0f}%"
            if matches else f"{info} ｜ 无足够历史可比窗口")
        self.pat_table.setRowCount(len(matches))
        for r_, p in enumerate(matches):
            vals = (p["start_date"], p["end_date"], f"{p['similarity_pct']}%",
                    f"{p['forward_ret_pct']:+.2f}%", f"{p['forward_dd_pct']:.2f}%",
                    f"+{p['forward_max_up_pct']:.2f}%")
            for c, val in enumerate(vals):
                self.pat_table.setItem(r_, c, QTableWidgetItem(str(val)))
