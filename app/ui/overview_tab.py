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

        # 模块五：板块热力图（Treemap，面积≈成交额，颜色=涨跌幅，红涨绿跌）
        from app.ui.sector_treemap import SectorTreemap
        heat_title = QLabel("板块热力图 · 面积≈成交额 · 颜色=涨跌幅")
        heat_title.setStyleSheet("color:#8B949E; font-size:12px; margin-top:8px;")
        self.heatmap = SectorTreemap()
        self.heatmap.setMinimumHeight(200)
        self.heat_hint = QLabel("（悬停查看板块涨跌幅）")
        self.heat_hint.setStyleSheet("color:#8B949E; font-size:11px;")
        self.heatmap.hovered.connect(self.heat_hint.setText)
        btn_heat = QPushButton("刷新板块")
        btn_heat.clicked.connect(self.heatmap.refresh)

        hrow = QHBoxLayout()
        hrow.addWidget(heat_title)
        hrow.addStretch(1)
        hrow.addWidget(btn_heat)

        v = QVBoxLayout(self)
        v.addLayout(top)
        v.addWidget(self.table)
        v.addLayout(hrow)
        v.addWidget(self.heatmap, 1)
        v.addWidget(self.heat_hint)
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
            # 涨跌色统一走主题惯例（默认 A股红涨绿跌）
            from app.ui.ui_theme import down_color, up_color
            item_chg.setForeground(QColor(up_color()) if chg >= 0
                                   else QColor(down_color()))
            self.table.setItem(r, 2, item_chg)
            self.table.setItem(r, 3, QTableWidgetItem(sig))
        self.btn.setEnabled(True)
