# -*- coding: utf-8 -*-
"""股票搜索对话框：多维度智能搜索（代码/名称/拼音/模糊匹配）。"""
from __future__ import annotations

import logging

from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLineEdit, QListWidget,
    QListWidgetItem, QLabel, QPushButton,
)

from core.search import stock_index

log = logging.getLogger("stockai.ui.stock_search")


class _StockLoadWorker(QThread):
    """后台加载全市场股票并构建索引。"""
    done = Signal(list)

    def run(self):
        # 先从SQLite加载
        stocks = stock_index.load_index()
        if stocks:
            self.done.emit(stocks)
            return
        # SQLite没有，从AKShare拉取
        try:
            import akshare as ak
            df = ak.stock_zh_a_spot_em()
            stocks = []
            for _, row in df.iterrows():
                code = str(row.get("代码", "")).strip()
                name = str(row.get("名称", "")).strip()
                if not code or not name:
                    continue
                if code.startswith(("60", "68", "90", "11", "13")):
                    market = "SH"
                elif code.startswith(("00", "30", "20")):
                    market = "SZ"
                elif code.startswith(("8", "4", "92")):
                    market = "BJ"
                else:
                    market = "SZ"
                stocks.append({
                    "code": code, "name": name,
                    "market": market, "ticker": f"{market}{code}",
                    "pinyin": stock_index.get_pinyin_abbr(name),
                })
            stock_index.build_index(stocks)
        except Exception as e:
            log.warning("获取全市场股票失败: %s", e)
        self.done.emit(stocks)


class StockSearchDialog(QDialog):
    """智能股票搜索：支持代码/名称/拼音/模糊匹配。"""

    selected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("搜索股票")
        self.setMinimumSize(560, 520)
        self._stocks: list[dict] = []
        self._debounce = QTimer()
        self._debounce.setSingleShot(True)
        self._debounce.timeout.connect(self._do_search)
        self._build_ui()
        self._load_stocks()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        row = QHBoxLayout()
        row.addWidget(QLabel("搜索："))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(
            "代码(600519) / 名称(茅台) / 拼音缩写(gzmt) / 英文(aapl)")
        self.search_input.textChanged.connect(self._on_input)
        self.search_input.returnPressed.connect(self._select_first)
        row.addWidget(self.search_input)
        layout.addLayout(row)

        self.result_list = QListWidget()
        self.result_list.itemDoubleClicked.connect(self._on_double_click)
        self.result_list.setMinimumHeight(350)
        layout.addWidget(self.result_list)

        btn_row = QHBoxLayout()
        self.status_label = QLabel("加载中…")
        btn_row.addWidget(self.status_label)
        btn_row.addStretch()
        btn_ok = QPushButton("选中")
        btn_ok.clicked.connect(self._select_first)
        btn_row.addWidget(btn_ok)
        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)
        layout.addLayout(btn_row)

    def _load_stocks(self):
        self.worker = _StockLoadWorker()
        self.worker.done.connect(self._on_loaded)
        self.worker.start()

    def _on_loaded(self, stocks: list[dict]):
        self._stocks = stocks
        if stocks:
            self.status_label.setText(f"共 {len(stocks)} 只股票，输入关键词筛选")
            # 显示搜索历史
            history = stock_index.get_search_history(5)
            if history:
                for h in history:
                    item = QListWidgetItem(f"🕐 {h['query']} → {h['code']}")
                    item.setData(Qt.UserRole, h["code"])
                    self.result_list.addItem(item)
            else:
                self._show_all()
        else:
            self.status_label.setText("加载失败，请检查网络")
        self.search_input.setFocus()

    def _show_all(self):
        self.result_list.clear()
        for s in self._stocks[:50]:
            self._add_item(s)

    def _add_item(self, s: dict):
        item = QListWidgetItem(
            f"{s['ticker']}  {s['name']}  [{s.get('match_type', '')}]")
        item.setData(Qt.UserRole, s["ticker"])
        self.result_list.addItem(item)

    def _on_input(self, text: str):
        # 防抖200ms
        self._debounce.start(200)

    def _do_search(self):
        text = self.search_input.text().strip()
        self.result_list.clear()
        if not text:
            self._show_all()
            return
        results = stock_index.search_stocks(text, self._stocks, limit=30)
        if results:
            for s in results:
                self._add_item(s)
            self.status_label.setText(
                f"找到 {len(results)} 只匹配股票")
        else:
            self.status_label.setText(
                "未找到匹配股票，可直接输入代码后回车")

    def _select_first(self):
        if self.result_list.count() > 0:
            self.result_list.setCurrentRow(0)
            self._on_double_click(self.result_list.currentItem())

    def _on_double_click(self, item: QListWidgetItem):
        if item:
            ticker = item.data(Qt.UserRole)
            # 记录搜索历史
            stock_index.log_search(self.search_input.text().strip(), ticker)
            self.selected.emit(ticker)
            self.accept()
