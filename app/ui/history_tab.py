# -*- coding: utf-8 -*-
"""决策记录页：展示历史分析决策（来源 SQLite decisions 表）。"""
from __future__ import annotations

from PyQt6.QtWidgets import (QHBoxLayout, QHeaderView, QPushButton, QTableWidget,
                             QTableWidgetItem, QVBoxLayout, QWidget)

from core.memory.decision_log import list_recent

_COLS = ["#", "时间", "标的", "数据截止", "价格", "动作", "仓位%", "置信%"]


class HistoryTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        v = QVBoxLayout(self)
        bar = QHBoxLayout()
        btn = QPushButton("刷新")
        btn.clicked.connect(self.refresh)
        bar.addWidget(btn)
        bar.addStretch()
        v.addLayout(bar)

        self.table = QTableWidget(0, len(_COLS))
        self.table.setHorizontalHeaderLabels(_COLS)
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        v.addWidget(self.table, 1)
        self.refresh()

    def refresh(self) -> None:
        try:
            rows = list_recent(limit=100)
        except Exception:  # noqa: BLE001
            rows = []
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            vals = (row.get("id"), str(row.get("ts", ""))[:19], row.get("ticker"),
                    row.get("asof"), row.get("price"), row.get("action"),
                    row.get("position_pct"), row.get("confidence"))
            for c, val in enumerate(vals):
                self.table.setItem(r, c, QTableWidgetItem("—" if val is None else str(val)))
