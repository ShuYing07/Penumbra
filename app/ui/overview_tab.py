# -*- coding: utf-8 -*-
"""宏观市场概览页：主要宽基指数实时点位/涨跌一览。"""
from __future__ import annotations

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (QHeaderView, QHBoxLayout, QLabel, QPushButton,
                             QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from core.data.market_overview import list_market_indices


class _FetchWorker(QThread):
    done = pyqtSignal(list)

    def run(self) -> None:
        try:
            self.done.emit(list_market_indices())
        except Exception as e:  # noqa: BLE001
            self.done.emit([{"name": "加载失败", "chg_pct": 0, "price": 0, "code": str(e)[:40]}])


class OverviewTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker: _FetchWorker | None = None
        self._build()

    def _build(self) -> None:
        top = QHBoxLayout()
        top.addWidget(QLabel("主要宽基指数 · 实时"))
        self.btn = QPushButton("刷新")
        self.btn.clicked.connect(self.refresh)
        top.addWidget(self.btn)
        top.addStretch()

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["指数", "最新点位", "涨跌幅%", "信号"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        v = QVBoxLayout(self)
        v.addLayout(top)
        v.addWidget(self.table)
        self.refresh()

    def refresh(self) -> None:
        if self._worker and self._worker.isRunning():
            return
        self.btn.setEnabled(False)
        self._worker = _FetchWorker()
        self._worker.done.connect(self._on_done)
        self._worker.start()

    def _on_done(self, rows: list) -> None:
        self.table.setRowCount(0)
        for it in rows:
            r = self.table.rowCount()
            self.table.insertRow(r)
            chg = it.get("chg_pct", 0) or 0
            sig = "偏强" if chg >= 0.5 else ("偏弱" if chg <= -0.5 else "平")
            self.table.setItem(r, 0, QTableWidgetItem(str(it.get("name", ""))))
            self.table.setItem(r, 1, QTableWidgetItem(str(it.get("price", ""))))
            item_chg = QTableWidgetItem(f"{chg:+.2f}")
            # 国内红涨绿跌
            item_chg.setForeground(QColor("#e5534b") if chg >= 0 else QColor("#26c07a"))
            self.table.setItem(r, 2, item_chg)
            self.table.setItem(r, 3, QTableWidgetItem(sig))
        self.btn.setEnabled(True)
