# -*- coding: utf-8 -*-
"""工作流编辑器（模块五 · 参考 FinceptTerminal 节点编辑器）。

左侧为可拖拽排序的节点列表（数据获取→指标计算→AI分析→回测→报告），
右侧为执行结果与生成的报告。节点执行走 core.workflow.runner（确定性
降级安全）；节点链可保存/加载到本地 JSON。
"""
from __future__ import annotations

import json
import logging
import os

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
                             QPlainTextEdit, QPushButton, QSplitter,
                             QVBoxLayout, QWidget)

from app.ui.ui_theme import ACCENT, BG_CARD, BORDER, TEXT_MAIN, TEXT_SUB

log = logging.getLogger("stockai.ui.workflow")

_FLOW_FILE = os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))), "data", "workflow_flows.json")

_NODE_LABELS = {
    "fetch_data": "📥 数据获取", "calc_indicators": "🧮 指标计算",
    "ai_analysis": "🤖 AI 分析", "run_backtest": "🧪 回测验证",
    "gen_report": "📄 生成报告",
}


class WorkflowTab(QWidget):
    """拖拽排序节点链 + 运行 + 报告展示。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build()
        self._load_flow()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        title = QLabel("分析工作流编辑器")
        title.setStyleSheet(f"color:{TEXT_MAIN};font-size:16px;font-weight:bold;")
        root.addWidget(title)

        hint = QLabel("拖拽左侧节点排序（数据获取 → 指标计算 → AI 分析 → 回测 → 报告），"
                      "点击「运行工作流」按顺序执行；节点可选中后删除。")
        hint.setStyleSheet(f"color:{TEXT_SUB};")
        hint.setWordWrap(True)
        root.addWidget(hint)

        split = QSplitter(Qt.Orientation.Horizontal)
        # 左：节点列表
        left = QWidget()
        lv = QVBoxLayout(left)
        self.list = QListWidget()
        self.list.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.list.setStyleSheet(
            f"QListWidget{{background:{BG_CARD};border:1px solid {BORDER};"
            f"border-radius:8px;padding:4px;}}"
            f"QListWidget::item{{color:{TEXT_MAIN};padding:6px;}}"
            f"QListWidget::item:selected{{background:{ACCENT}22;}}")
        lv.addWidget(self.list)
        count_lbl = QLabel(f"拖拽排序 · 共 {len(_NODE_LABELS)} 个节点")
        count_lbl.setStyleSheet(f"color:{TEXT_SUB};")
        lv.addWidget(count_lbl)
        left_btns = QHBoxLayout()
        b_run = QPushButton("▶ 运行工作流")
        b_run.setStyleSheet(_btn(primary=True))
        b_run.clicked.connect(self._run)
        b_add = QPushButton("重置为默认")
        b_add.setStyleSheet(_btn())
        b_add.clicked.connect(self._reset)
        b_save = QPushButton("保存流程")
        b_save.setStyleSheet(_btn())
        b_save.clicked.connect(self._save)
        left_btns.addWidget(b_run)
        left_btns.addWidget(b_add)
        left_btns.addWidget(b_save)
        lv.addLayout(left_btns)
        split.addWidget(left)

        # 右：报告/结果
        right = QWidget()
        rv = QVBoxLayout(right)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setStyleSheet(
            f"QPlainTextEdit{{background:{BG_CARD};border:1px solid {BORDER};"
            f"border-radius:8px;color:{TEXT_MAIN};font-family:Consolas;"
            f"font-size:12px;padding:8px;}}")
        rv.addWidget(QLabel("运行结果 / 报告"))
        rv.addWidget(self.output)
        split.addWidget(right)
        split.setSizes([260, 640])
        root.addWidget(split, 1)

    # ---------------- 操作 ----------------
    def _nodes(self) -> list[str]:
        return [self.list.item(i).data(Qt.ItemDataRole.UserRole)
                for i in range(self.list.count())]

    def _run(self) -> None:
        from core.workflow.runner import run_workflow
        nodes = self._nodes() or ["fetch_data", "gen_report"]
        try:
            r = run_workflow(nodes, ticker="600519")
            self.output.setPlainText(r["report"])
            self.output.appendPlainText("\n\n—— 节点执行状态 ——")
            for s in r["results"]:
                self.output.appendPlainText(
                    f"[{s['status']}] {s.get('summary', '')}")
        except Exception as e:  # noqa: BLE001
            self.output.setPlainText(f"工作流执行失败：{e}")

    def _reset(self) -> None:
        from core.workflow.runner import DEFAULT_FLOW
        self.list.clear()
        for n in DEFAULT_FLOW:
            it = QListWidgetItem(_NODE_LABELS.get(n, n))
            it.setData(Qt.ItemDataRole.UserRole, n)
            self.list.addItem(it)

    def _save(self) -> None:
        try:
            os.makedirs(os.path.dirname(_FLOW_FILE), exist_ok=True)
            with open(_FLOW_FILE, "w", encoding="utf-8") as f:
                json.dump({"nodes": self._nodes()}, f, ensure_ascii=False)
            self.output.appendPlainText("✅ 流程已保存到本地")
        except Exception as e:  # noqa: BLE001
            self.output.appendPlainText(f"保存失败：{e}")

    def _load_flow(self) -> None:
        try:
            if os.path.exists(_FLOW_FILE):
                with open(_FLOW_FILE, "r", encoding="utf-8") as f:
                    nodes = json.load(f).get("nodes") or []
                if nodes:
                    for n in nodes:
                        it = QListWidgetItem(_NODE_LABELS.get(n, n))
                        it.setData(Qt.ItemDataRole.UserRole, n)
                        self.list.addItem(it)
                    return
        except Exception as e:  # noqa: BLE001
            log.debug("流程加载失败：%s", e)
        self._reset()


def _btn(primary: bool = False) -> str:
    if primary:
        return (f"QPushButton{{background:{ACCENT};color:#0A0C10;"
                f"border:none;border-radius:6px;padding:6px 12px;font-weight:bold;}}"
                f"QPushButton:hover{{background:{ACCENT}CC;}}")
    return (f"QPushButton{{background:transparent;color:{ACCENT};"
            f"border:1px solid {ACCENT};border-radius:6px;padding:6px 12px;}}"
            f"QPushButton:hover{{background:{ACCENT}22;}}")
