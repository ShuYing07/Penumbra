# -*- coding: utf-8 -*-
"""产业概念图谱标签页：按股票查概念 / 按概念查股票。

合规定位：仅展示股票与概念板块的客观归属关系，不构成任何投资建议。
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from core.data import industry_graph as ig


class _Worker(QThread):
    done = pyqtSignal(list, str)  # rows, title
    err = pyqtSignal(str)

    def __init__(self, mode: str, key: str):
        super().__init__()
        self.mode, self.key = mode, key

    def run(self):
        try:
            if self.mode == "stock":
                rows = ig.get_concepts_by_stock(self.key)
                self.done.emit([{"code": "-", "name": c} for c in rows],
                               f"{self.key} 所属概念（{len(rows)}个）")
            else:
                rows = ig.get_stocks_by_concept(self.key)
                self.done.emit(rows, f"概念「{self.key}」成分股（{len(rows)}只）")
        except Exception as e:  # noqa: BLE001
            self.err.emit(str(e))


class IndustryTab(QWidget):
    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)

        top = QHBoxLayout()
        self.mode = QComboBox()
        self.mode.addItems(["按概念查股票", "按股票查概念"])
        self.input = QLineEdit()
        self.input.setPlaceholderText("输入概念名如「白酒」，或股票代码如 600519")
        self.btn = QPushButton("查询")
        self.build_btn = QPushButton("建立全量图谱(首次较慢)")
        self.btn.clicked.connect(self._query)
        self.build_btn.clicked.connect(self._build)
        top.addWidget(self.mode)
        top.addWidget(self.input, 1)
        top.addWidget(self.btn)
        top.addWidget(self.build_btn)
        lay.addLayout(top)

        self.status = QLabel("")
        self.status.setStyleSheet("color:#8B949E;")
        lay.addWidget(self.status)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["代码", "名称"])
        self.table.horizontalHeader().setStretchLastSection(True)
        lay.addWidget(self.table)

        lay.addWidget(QLabel("⚠️ 本页仅展示概念板块客观归属，不构成投资建议。"))

    def _query(self):
        key = self.input.text().strip()
        if not key:
            self.status.setText("请输入关键词")
            return
        self.btn.setEnabled(False)
        mode = self.mode.currentText()
        self.status.setText("查询中…")
        self._w = _Worker(mode, key)
        self._w.done.connect(self._show)
        self._w.err.connect(self._fail)
        self._w.start()

    def _show(self, rows, title):
        self.status.setText(title)
        self.table.setRowCount(0)
        for r in rows:
            rc = self.table.rowCount()
            self.table.insertRow(rc)
            self.table.setItem(rc, 0, QTableWidgetItem(r.get("code", "")))
            self.table.setItem(rc, 1, QTableWidgetItem(r.get("name", "")))
        self.btn.setEnabled(True)

    def _fail(self, msg):
        self.status.setText("查询失败：" + msg + "（本机网络对东财接口偶发断连，可稍后重试）")
        self.btn.setEnabled(True)

    def _build(self):
        self.build_btn.setEnabled(False)
        self.status.setText("正在后台建立全量概念图谱，请耐心等待…")
        def cb(n):
            self.status.setText(f"全量图谱完成，写入 {n} 行" if n >= 0 else "构建失败，请检查网络")
            self.build_btn.setEnabled(True)
        ig.build_full_graph_async(cb)
