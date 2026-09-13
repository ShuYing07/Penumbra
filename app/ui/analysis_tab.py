# -*- coding: utf-8 -*-
"""分析页：输入标的 → 后台线程跑多智能体管线 → 节点进度 + Markdown 报告。"""
from __future__ import annotations

from datetime import datetime

from PyQt6.QtCore import QThread, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QLabel,
                             QLineEdit, QListWidget, QMessageBox, QPushButton,
                             QSplitter, QTextBrowser, QVBoxLayout, QWidget)

from app.ui.local_model_dialog import LocalModelDialog
from core import llm_local
from core.agents.graph import NODE_LABELS, run_analysis
from core.config import REPORT_DIR
from core.llm import LLMRunner
from core.memory.reflection import evaluate_pending
from core.portfolio import paper
from core.report import render

_BACKENDS = [("云端 DeepSeek（质量高）", "deepseek"),
             ("本地模型（完全离线·免费）", "local"),
             ("自动（云端失败切本地）", "auto")]

_NODE_KEYS = list(NODE_LABELS)
_LOG_LIMIT = 200  # 采集日志最多保留行数


class AnalysisWorker(QThread):
    """在后台线程执行完整分析管线，全部结果经信号回 UI 线程。"""

    stage = pyqtSignal(str)            # 数据采集阶段日志
    node_done = pyqtSignal(str, bool)  # (节点key, 是否降级)
    ok = pyqtSignal(dict)              # {"state":…, "decision_id":…}
    err = pyqtSignal(str)

    def __init__(self, ticker: str, mock: bool, backend: str = "deepseek", parent=None):
        super().__init__(parent)
        self.ticker = ticker
        self.mock = mock
        self.backend = backend

    def run(self) -> None:
        try:
            runner = LLMRunner(mock=True) if self.mock \
                else LLMRunner(backend=self.backend)
        except Exception as e:  # noqa: BLE001
            self.err.emit(str(e))
            return
        if runner.mock:
            mode = "离线MOCK（不调用大模型）"
        elif self.backend == "local":
            mode = f"本地模型 {runner.local_model}（离线·免费）"
        elif self.backend == "auto":
            mode = f"自动切换（云端 {runner.model} → 本地）"
        else:
            mode = "DeepSeek云端 " + runner.model
        self.stage.emit(f"LLM 模式：{mode}")

        # 先评估到期决策（本地库+缓存行情，失败不阻塞分析）
        try:
            evaled = evaluate_pending(limit=10)
            if evaled:
                self.stage.emit(f"决策复盘：已评估 {len(evaled)} 条到期决策并写入反思")
        except Exception as e:  # noqa: BLE001
            self.stage.emit(f"决策复盘跳过：{type(e).__name__}: {e}")

        def cb(kind, payload):
            if kind == "data":
                self.stage.emit(str(payload))
            elif kind == "node":
                node_key, degraded = payload
                self.node_done.emit(node_key, degraded)

        try:
            result = run_analysis(self.ticker, runner=runner, progress_cb=cb)
            self.ok.emit(result)
        except Exception as e:  # noqa: BLE001
            self.err.emit(f"{type(e).__name__}: {e}")


class AnalysisTab(QWidget):
    analysis_finished = pyqtSignal(dict)  # 广播给主窗口联动（刷新历史/K线）

    def __init__(self, parent=None):
        super().__init__(parent)
        self.worker: AnalysisWorker | None = None
        self._last_md: str = ""
        self._build_ui()

    # ---------------- UI ----------------
    def _build_ui(self) -> None:
        top = QHBoxLayout()
        top.addWidget(QLabel("标的："))
        self.input = QLineEdit()
        self.input.setPlaceholderText("SH600519 / AAPL / 0700.HK / SH510300 / BTC-USD")
        self.input.setMaximumWidth(230)
        self.input.returnPressed.connect(self._start)
        top.addWidget(self.input)
        self.btn_run = QPushButton("开始分析")
        self.btn_run.clicked.connect(self._start)
        top.addWidget(self.btn_run)
        self.mock_box = QCheckBox("离线演示(MOCK)")
        self.mock_box.setToolTip("勾选后不调用 DeepSeek，用本地桩数据演示完整流程")
        top.addWidget(self.mock_box)
        self.paper_box = QCheckBox("决策自动入模拟盘")
        self.paper_box.setChecked(True)
        self.paper_box.setToolTip("分析完成后按最终建议自动在模拟盘买入/清仓（虚拟资金，非实盘）")
        top.addWidget(self.paper_box)
        top.addWidget(QLabel("引擎："))
        self.engine_box = QComboBox()
        for label, _ in _BACKENDS:
            self.engine_box.addItem(label)
        self.engine_box.setToolTip("云端=DeepSeek（按token计费）；本地=完全离线免费；自动=云端不可用时切本地")
        top.addWidget(self.engine_box)
        self.btn_local = QPushButton("本地模型…")
        self.btn_local.setToolTip("检测 Ollama、下载/管理本地模型")
        self.btn_local.clicked.connect(self._open_local_manager)
        top.addWidget(self.btn_local)
        top.addStretch()
        self.info = QLabel("")
        top.addWidget(self.info)

        split = QSplitter()
        self.progress = QListWidget()
        self.progress.setMaximumWidth(340)
        self._reset_progress()
        split.addWidget(self.progress)
        self.report = QTextBrowser()
        split.addWidget(self.report)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)

        bottom = QHBoxLayout()
        self.btn_export = QPushButton("导出报告为…")
        self.btn_export.clicked.connect(self._export)
        self.btn_export.setEnabled(False)
        bottom.addWidget(self.btn_export)
        bottom.addStretch()

        v = QVBoxLayout(self)
        v.addLayout(top)
        v.addWidget(split, 1)
        v.addLayout(bottom)

    def _reset_progress(self) -> None:
        self.progress.clear()
        for key in _NODE_KEYS:
            self.progress.addItem(f"⏳ {NODE_LABELS[key]}")

    # ---------------- 流程 ----------------
    def _start(self) -> None:
        if self.worker and self.worker.isRunning():
            return
        ticker = self.input.text().strip().upper()
        if not ticker:
            self.info.setText("请输入标的代码，如 SH600519")
            return
        mock = self.mock_box.isChecked()
        backend = _BACKENDS[self.engine_box.currentIndex()][1]
        # 本地/自动引擎前置检查（缺 Ollama 或模型时先引导，不白跑管线）
        if not mock and backend in ("local", "auto"):
            from core.config import LOCAL_MODEL, LOCAL_MODEL_SMALL

            if not llm_local.is_running() and not llm_local.ensure_started():
                QMessageBox.information(
                    self, "本地引擎不可用",
                    "未检测到 Ollama 服务。请先安装并启动 Ollama（官网一键安装），"
                    "再下载模型。\n\n下载地址：https://ollama.com/download/windows")
                self._open_local_manager()
                return
            if not (llm_local.has_model(LOCAL_MODEL)
                    or llm_local.has_model(LOCAL_MODEL_SMALL)):
                ret = QMessageBox.question(
                    self, "本地模型未下载",
                    f"本地引擎需要先下载模型（推荐 {LOCAL_MODEL}，约 4.7GB，仅一次）。\n"
                    "是否现在打开模型管理下载？\n（云端引擎无需下载，可切回『云端』直接使用）")
                if ret == QMessageBox.StandardButton.Yes:
                    self._open_local_manager()
                return
        self._reset_progress()
        self.btn_run.setEnabled(False)
        self.btn_export.setEnabled(False)
        self.report.clear()
        self.info.setText("分析中…（首次联网采集与大模型推理需要一些时间）")
        self.worker = AnalysisWorker(ticker, mock, backend)
        self.worker.stage.connect(self._on_stage)
        self.worker.node_done.connect(self._on_node)
        self.worker.ok.connect(self._on_ok)
        self.worker.err.connect(self._on_err)
        self.worker.start()

    # ---------------- 槽 ----------------
    def _open_local_manager(self) -> None:
        dlg = LocalModelDialog(self)
        dlg.exec()

    @pyqtSlot(str)
    def _on_stage(self, text: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self.progress.addItem(f"· {stamp} {text}")
        while self.progress.count() > _LOG_LIMIT + len(_NODE_KEYS):
            self.progress.takeItem(len(_NODE_KEYS))

    @pyqtSlot(str, bool)
    def _on_node(self, key: str, degraded: bool) -> None:
        idx = _NODE_KEYS.index(key)
        mark = "⚠️" if degraded else "✅"
        self.progress.item(idx).setText(f"{mark} {NODE_LABELS[key]}")

    @pyqtSlot(dict)
    def _on_ok(self, result: dict) -> None:
        state = result["state"]
        md = render(state)
        self._last_md = md
        self.report.setMarkdown(md)
        try:
            out = REPORT_DIR / f"{state.get('ticker')}_{state.get('asof', '')}.md"
            out.write_text(md, encoding="utf-8")
            saved = f"，已存 {out.name}"
        except Exception as e:  # noqa: BLE001
            saved = f"（报告落盘失败：{e}）"
        if state.get("errors"):
            self.progress.addItem(f"⚠️ 降级节点：{', '.join(state['errors'])}")
        # 模拟盘自动执行
        if self.paper_box.isChecked():
            try:
                state["_decision_id"] = result.get("decision_id")
                trade = paper.execute(state)
                if trade:
                    self.progress.addItem(
                        f"💰 模拟盘：{trade['side']} {trade['ticker']} "
                        f"{trade['shares']}股 @ {trade['price']}")
            except Exception as e:  # noqa: BLE001
                self.progress.addItem(f"⚠️ 模拟盘执行失败：{e}")
        f = state.get("final", {})
        self.info.setText(f"完成：{f.get('action')} 仓位 {f.get('position_pct')}%"
                          f"{saved}（决策 #{result.get('decision_id')}）")
        self.btn_run.setEnabled(True)
        self.btn_export.setEnabled(True)
        self.analysis_finished.emit(result)

    @pyqtSlot(str)
    def _on_err(self, msg: str) -> None:
        self.info.setText(f"失败：{msg}")
        self.progress.addItem(f"❌ {msg}")
        self.btn_run.setEnabled(True)

    def _export(self) -> None:
        if not self._last_md:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "导出分析报告", str(REPORT_DIR / "report.md"), "Markdown (*.md);;所有文件 (*.*)")
        if path:
            with open(path, "w", encoding="utf-8") as fp:
                fp.write(self._last_md)
            self.info.setText(f"已导出：{path}")
