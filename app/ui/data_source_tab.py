# -*- coding: utf-8 -*-
"""数据源管理 Tab（企业版）：第三方数据源订阅 + CSV/Excel 导入。

- 左侧：数据源目录（内置 Wind/Tushare/Polygon/Alpha Vantage/AkShare），订阅/退订；
- 右侧：本地 CSV/Excel 导入为行情缓存（供回测/分析使用）。
"""
from __future__ import annotations

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QTableWidget, QTableWidgetItem, QPushButton,
                             QLineEdit, QFileDialog, QMessageBox, QSplitter)
from PyQt6.QtCore import Qt

from app.ui.ui_theme import BG_CARD, BORDER, TEXT_MAIN, TEXT_SUB, ACCENT


class DataSourceTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build()

    def _build(self) -> None:
        lay = QVBoxLayout(self)
        title = QLabel("🔌 数据源管理（企业版）")
        title.setStyleSheet(f"font-size:15px; font-weight:bold; color:{TEXT_MAIN};")
        lay.addWidget(title)
        tip = QLabel("订阅第三方数据源（本地状态，不联网结算）；或导入本地 CSV/Excel 行情。")
        tip.setStyleSheet(f"color:{TEXT_SUB}; font-size:11px;")
        lay.addWidget(tip)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        # 左：数据源目录
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.addWidget(QLabel("数据源目录"))
        self.catalog = QTableWidget(0, 3)
        self.catalog.setStyleSheet(
            f"QTableWidget {{ background:{BG_CARD}; border:1px solid {BORDER};"
            f" border-radius:8px; color:{TEXT_MAIN}; gridline-color:{BORDER}; }}")
        self.catalog.horizontalHeader().setStretchLastSection(True)
        ll.addWidget(self.catalog, 1)
        row = QHBoxLayout()
        btn_sub = QPushButton("订阅所选")
        btn_sub.setStyleSheet(f"background:{ACCENT}; color:#0A0E17; border-radius:6px; padding:6px 10px;")
        btn_sub.clicked.connect(self._subscribe)
        row.addWidget(btn_sub)
        btn_unsub = QPushButton("退订")
        btn_unsub.clicked.connect(self._unsubscribe)
        row.addWidget(btn_unsub)
        btn_refresh = QPushButton("刷新状态")
        btn_refresh.clicked.connect(self.refresh)
        row.addWidget(btn_refresh)
        ll.addLayout(row)
        self.status_label = QLabel("")
        self.status_label.setStyleSheet(f"color:{TEXT_SUB}; font-size:11px;")
        ll.addWidget(self.status_label)

        # 右：导入
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.addWidget(QLabel("本地数据导入"))
        rl.addWidget(QLabel("支持 CSV（UTF-8）或 Excel，列：日期/开盘/最高/最低/收盘[/成交量]"))
        row2 = QHBoxLayout()
        self.ticker_edit = QLineEdit()
        self.ticker_edit.setPlaceholderText("标的代码，如 SH600519 / MYDATA")
        row2.addWidget(self.ticker_edit, 1)
        btn_file = QPushButton("选择文件并导入")
        btn_file.setStyleSheet(f"background:{ACCENT}; color:#0A0E17; border-radius:6px; padding:6px 12px;")
        btn_file.clicked.connect(self._import_file)
        row2.addWidget(btn_file)
        rl.addLayout(row2)
        self.import_log = QLabel("（未导入）")
        self.import_log.setStyleSheet(
            f"background:{BG_CARD}; border:1px solid {BORDER}; border-radius:8px;"
            f" color:{TEXT_MAIN}; padding:10px;")
        self.import_log.setWordWrap(True)
        self.import_log.setMinimumHeight(180)
        rl.addWidget(self.import_log, 1)

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([400, 460])
        lay.addWidget(splitter, 1)
        self.refresh()

    def refresh(self) -> None:
        from core.data_marketplace import list_catalog, list_subscriptions
        self.catalog.setRowCount(0)
        self.catalog.setHorizontalHeaderLabels(["ID", "名称", "说明"])
        for s in list_catalog():
            r = self.catalog.rowCount()
            self.catalog.insertRow(r)
            for j, v in enumerate([s["id"], s["name"], s["desc"]]):
                self.catalog.setItem(r, j, QTableWidgetItem(str(v)))
        subs = list_subscriptions("local")
        self.status_label.setText(
            "已订阅：" + ("、".join(s["source_id"] for s in subs if s["status"] == "active")
                          or "（无）"))

    def _selected_source(self) -> str | None:
        row = self.catalog.currentRow()
        if row < 0:
            return None
        item = self.catalog.item(row, 0)
        return item.text() if item else None

    def _subscribe(self) -> None:
        src = self._selected_source()
        if not src:
            QMessageBox.information(self, "提示", "请先在列表中选择数据源")
            return
        from core.data_marketplace import subscribe
        subscribe("local", src)
        self.refresh()
        QMessageBox.information(self, "完成", f"已订阅 {src}")

    def _unsubscribe(self) -> None:
        src = self._selected_source()
        if not src:
            return
        from core.data_marketplace import unsubscribe
        unsubscribe("local", src)
        self.refresh()

    def _import_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择行情文件", "",
            "数据文件 (*.csv *.xlsx);;CSV (*.csv);;Excel (*.xlsx)")
        if not path:
            return
        ticker = self.ticker_edit.text().strip()
        if not ticker:
            QMessageBox.warning(self, "提示", "请先填写标的代码")
            return
        try:
            from core.data_connector import parse_csv, parse_excel, import_to_cache
            df = parse_csv(path) if path.lower().endswith(".csv") else parse_excel(path)
            n = import_to_cache(df, ticker)
            self.import_log.setText(
                f"✅ 导入成功：{path}\n{ticker} 共 {n} 行\n"
                f"日期 {df.index.min().date()} ~ {df.index.max().date()}\n"
                f"可直接在 K线图/回测 中使用 {ticker}")
        except Exception as e:  # noqa: BLE001
            self.import_log.setText(f"❌ 导入失败：{type(e).__name__}: {e}")
