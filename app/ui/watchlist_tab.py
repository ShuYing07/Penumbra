# -*- coding: utf-8 -*-
"""自选股/盯盘页：自选股列表 + 一句话盯盘条件 + 实时看板 + 桌面通知触发。

- 自选股按市场分组，持久化到 SQLite（core.watchlist.store）
- 一句话盯盘条件用规则引擎解析（core.watchlist.conditions），不调 LLM
- QTimer 按交易时段动态调频，后台 QThread 跑 engine.scan_all()
- 触发的标的经 triggered 信号发给主窗口托盘气泡；双击行 → analyze_requested
"""
from __future__ import annotations

import logging

from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QAction, QColor
from PyQt6.QtWidgets import (QCheckBox, QHBoxLayout, QHeaderView, QInputDialog,
                              QLabel, QLineEdit, QMenu, QMessageBox, QPushButton,
                              QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from core.config import DISCLAIMER, now_cn, refresh_interval
from core.data import service
from core.watchlist import conditions, engine, store

log = logging.getLogger("stockai.ui.watchlist")

_STATUS_COLOR = {
    "✅触发": "#c0392b",   # 红（警示）
    "⏳等待": "#7f8c8d",   # 灰
    "❌无效": "#d4ac0d",   # 黄
    "—无数据": "#bdc3c7",  # 淡灰
}


class _Scan(QThread):
    """后台扫描所有自选股。"""

    got = pyqtSignal(list)
    bad = pyqtSignal(str)

    def run(self) -> None:
        try:
            self.got.emit(engine.scan_all())
        except Exception as e:  # noqa: BLE001
            self.bad.emit(f"{type(e).__name__}: {e}")


class WatchlistTab(QWidget):
    analyze_requested = pyqtSignal(str)          # 双击/右键"加入分析"
    triggered = pyqtSignal(str, str)             # (标的, 文案) → 主窗口托盘

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker: _Scan | None = None
        self._watching = False
        self._build_ui()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        store.init()          # 幂等建表：自选股页首次实例化即保证表存在
        self._load_list()

    # ---------------- UI ----------------
    def _build_ui(self) -> None:
        top = QHBoxLayout()
        top.addWidget(QLabel("标的："))
        self.in_ticker = QLineEdit()
        self.in_ticker.setPlaceholderText("SH600519 / AAPL / 0700.HK / SH510300")
        self.in_ticker.setMaximumWidth(190)
        self.in_ticker.textChanged.connect(self._update_market_hint)
        self.in_ticker.returnPressed.connect(self._add)
        top.addWidget(self.in_ticker)
        top.addWidget(QLabel("市场："))
        self.lbl_market = QLabel("—")
        self.lbl_market.setStyleSheet("color: gray;")
        top.addWidget(self.lbl_market)
        top.addWidget(QLabel("盯盘条件："))
        self.in_cond = QLineEdit()
        self.in_cond.setPlaceholderText("跌破20日线 / RSI大于70 / 涨幅超过5% / MACD金叉")
        self.in_cond.returnPressed.connect(self._add)
        top.addWidget(self.in_cond, 1)
        top.addWidget(QLabel("备注："))
        self.in_note = QLineEdit()
        self.in_note.setMaximumWidth(110)
        top.addWidget(self.in_note)
        self.btn_add = QPushButton("添加")
        self.btn_add.clicked.connect(self._add)
        top.addWidget(self.btn_add)
        self.btn_test = QPushButton("测试条件")
        self.btn_test.setToolTip("解析条件，预览识别结果")
        self.btn_test.clicked.connect(self._test_cond)
        top.addWidget(self.btn_test)

        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(
            ["标的", "市场", "现价", "涨跌%", "盯盘条件", "状态", "距条件", "更新时间"])
        for c in (4, 6):
            self.table.horizontalHeader().setSectionResizeMode(c, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._menu)
        self.table.doubleClicked.connect(self._on_double_click)

        bar = QHBoxLayout()
        self.chk_watch = QCheckBox("开始盯盘（自动刷新+通知）")
        self.chk_watch.toggled.connect(self._toggle_watch)
        bar.addWidget(self.chk_watch)
        self.lbl_interval = QLabel("未盯盘")
        self.lbl_interval.setStyleSheet("color: gray;")
        bar.addWidget(self.lbl_interval)
        self.btn_refresh = QPushButton("手动刷新")
        self.btn_refresh.setToolTip("立即拉取所有自选股现价并评估盯盘条件")
        self.btn_refresh.clicked.connect(self.refresh)
        bar.addWidget(self.btn_refresh)
        bar.addStretch()

        lbl_dis = QLabel(DISCLAIMER + "  盯盘通知仅供参考")
        lbl_dis.setStyleSheet("color: gray;")

        v = QVBoxLayout(self)
        v.addLayout(top)
        v.addWidget(self.table, 1)
        v.addLayout(bar)
        v.addWidget(lbl_dis)

    # ---------------- 列表 ----------------
    def _update_market_hint(self) -> None:
        t = self.in_ticker.text().strip().upper()
        self.lbl_market.setText(service.market_of(t) if t else "—")

    def _load_list(self) -> None:
        rows = store.list_all()
        self.table.setRowCount(len(rows))
        for r, item in enumerate(rows):
            self._set_row(r, {
                "ticker": item["ticker"], "market": item["market"],
                "price": None, "chg_pct": None, "condition": item["condition"],
                "status": "—" if item["enabled"] else "已停用",
                "distance": "", "updated": item.get("added_at", "")[5:16],
            }, enabled=item["enabled"])

    def _set_row(self, r: int, d: dict, enabled: bool = True) -> None:
        price = d.get("price")
        chg = d.get("chg_pct")
        vals = [
            d["ticker"], d["market"],
            f"{price:.4g}" if price is not None else "—",
            f"{chg:+.2f}%" if chg is not None else "—",
            d.get("condition", "") or "—",
            d.get("status", ""),
            d.get("distance", ""),
            d.get("updated", ""),
        ]
        for c, val in enumerate(vals):
            cell = QTableWidgetItem(str(val))
            if c == 3 and chg is not None:               # 涨跌色：涨红跌绿
                cell.setForeground(QColor("#c0392b" if chg >= 0 else "#1e8449"))
            if c == 5:                                    # 状态色
                cell.setForeground(QColor(_STATUS_COLOR.get(val, "#000000")))
            if not enabled and c in (0,):
                cell.setForeground(QColor("#bdc3c7"))
            self.table.setItem(r, c, cell)

    # ---------------- 操作 ----------------
    def _add(self) -> None:
        from core.data.service import normalize_ticker
        raw = self.in_ticker.text().strip().upper()
        ticker = normalize_ticker(raw)
        if ticker != raw:
            self.in_ticker.setText(ticker)
        cond = self.in_cond.text().strip()
        note = self.in_note.text().strip()
        if not ticker:
            self._warn("请输入标的代码，如 600519")
            return
        market = service.market_of(ticker)
        if market == "UNKNOWN":
            self._warn(f"无法识别标的 {ticker} 的市场，请检查代码格式")
            return
        if store.add(ticker, market, cond, note):
            self.in_ticker.clear()
            self.in_cond.clear()
            self.in_note.clear()
            self._load_list()
            if self._watching:
                self.refresh()
        else:
            self._warn(f"{ticker} 已在自选股中")

    def _test_cond(self) -> None:
        text = self.in_cond.text().strip()
        if not text:
            self._warn("请先在「盯盘条件」输入框填写条件")
            return
        QMessageBox.information(self, "条件解析", conditions.preview(text))

    def _toggle_watch(self, on: bool) -> None:
        self._watching = on
        if on:
            self.refresh()
        else:
            self._timer.stop()
            self.lbl_interval.setText("未盯盘")

    def refresh(self) -> None:
        if self._worker and self._worker.isRunning():
            return
        self._worker = _Scan()
        self._worker.got.connect(self._on_scan)
        self._worker.bad.connect(self._on_bad)
        self._worker.start()

    # ---------------- 槽 ----------------
    @pyqtSlot(str)
    def _on_bad(self, msg: str) -> None:
        self.lbl_interval.setText(f"刷新失败：{msg}")

    @pyqtSlot(list)
    def _on_scan(self, rows: list) -> None:
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            self._set_row(r, {
                "ticker": row.ticker, "market": row.market,
                "price": row.price, "chg_pct": row.chg_pct,
                "condition": row.condition_text, "status": row.status,
                "distance": row.distance, "updated": row.updated_at,
            })
        # 触发的发通知
        for row in rows:
            if row.should_notify:
                self.triggered.emit(row.ticker,
                                    f"{row.ticker} {row.status}：{row.distance}")
        # 重新调度刷新间隔
        if self._watching and rows:
            markets = {row.market for row in rows}
            interval = min(refresh_interval(m, now_cn()) for m in markets)
            self._timer.start(interval * 1000)
            self.lbl_interval.setText(f"盯盘中 · 每 {interval} 秒")
        elif self._watching:
            self._timer.stop()
            self.lbl_interval.setText("无自选股")

    @pyqtSlot("QPoint")
    def _menu(self, pos) -> None:
        idx = self.table.indexAt(pos)
        if not idx.isValid():
            return
        ticker = self.table.item(idx.row(), 0).text()
        menu = QMenu(self)
        a_analyze = QAction("加入分析", self)
        a_edit = QAction("编辑条件…", self)
        a_toggle = QAction("停用/启用", self)
        a_del = QAction("删除", self)
        menu.addAction(a_analyze)
        menu.addAction(a_edit)
        menu.addAction(a_toggle)
        menu.addAction(a_del)
        chosen = menu.exec(self.table.viewport().mapToGlobal(pos))
        if chosen is a_analyze:
            self.analyze_requested.emit(ticker)
        elif chosen is a_edit:
            self._edit_cond(ticker)
        elif chosen is a_toggle:
            item = store.get(ticker)
            if item:
                store.set_enabled(ticker, not item["enabled"])
                self._load_list()
        elif chosen is a_del:
            store.remove(ticker)
            self._load_list()

    def _edit_cond(self, ticker: str) -> None:
        item = store.get(ticker)
        if not item:
            return
        text, ok = QInputDialog.getText(
            self, "编辑盯盘条件", f"{ticker} 的盯盘条件：",
            text=item["condition"])
        if ok:
            store.update(ticker, condition=text.strip())
            self._load_list()
            if self._watching:
                self.refresh()

    @pyqtSlot("QModelIndex")
    def _on_double_click(self, idx) -> None:
        ticker = self.table.item(idx.row(), 0).text()
        self.analyze_requested.emit(ticker)

    def _warn(self, msg: str) -> None:
        QMessageBox.information(self, "提示", msg)
