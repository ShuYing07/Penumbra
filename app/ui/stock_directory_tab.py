# -*- coding: utf-8 -*-
"""股票代码大全：全球18000+只 + 板块分类 + 代码/名称/拼音搜索 + 快捷复制 + AI搜索。"""
from __future__ import annotations

import json
import logging
import os
import sys

from PyQt6.QtCore import Qt, QThread, pyqtSignal as Signal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QLabel, QHeaderView, QComboBox,
    QDoubleSpinBox,
)

from core.search import stock_index

log = logging.getLogger("stockai.stock_directory")


def _load_all_stocks():
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
        for p in [os.path.join(base, "data", "all_stocks.json"),
                  os.path.join(base, "_internal", "data", "all_stocks.json")]:
            if os.path.exists(p):
                with open(p, "r", encoding="utf-8") as f:
                    return json.load(f)
    dev = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), "data", "all_stocks.json")
    if os.path.exists(dev):
        with open(dev, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


class _AISearchWorker(QThread):
    done = Signal(str)
    failed = Signal(str)

    def __init__(self, query: str):
        super().__init__()
        self.query = query

    def run(self):
        try:
            import requests
            prompt = (f'你是一个股票查询助手。用户说："{self.query}"\n'
                      f'请返回用户想查的股票代码（6位数字或美股ticker），只返回代码。')
            r = requests.post(
                "http://localhost:11434/api/generate",
                json={"model": "qwen2.5:7b-instruct-q4_K_M",
                      "prompt": prompt, "stream": False,
                      "options": {"temperature": 0.1}},
                timeout=30,
                proxies={"http": None, "https": None},
            )
            import re
            code = r.json().get("response", "").strip()
            m = re.search(r"[A-Z]{1,5}|\d{6}", code.upper())
            if m:
                self.done.emit(m.group())
            else:
                self.failed.emit(f"AI返回: {code}")
        except Exception as e:
            self.failed.emit(str(e))


class _ScreenerWorker(QThread):
    done = Signal(list, str)
    failed = Signal(str)

    def __init__(self, cond: dict):
        super().__init__()
        self.cond = cond

    def run(self):
        try:
            from core.screener import run_screener
            res = run_screener(**self.cond)
            self.done.emit(res["hits"], res.get("note", ""))
        except Exception as e:
            self.failed.emit(f"{type(e).__name__}: {e}")


class StockDirectoryTab(QWidget):
    add_watchlist = Signal(str)  # 双击行 → 主窗口加入自选

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stocks = []
        self._build_ui()
        self._init_stocks()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel("📋 股票大全"))
        top.addSpacing(10)

        self.market_box = QComboBox()
        self.market_box.addItems(["全部市场", "A股", "港股", "美股"])
        self.market_box.currentTextChanged.connect(self._filter)
        top.addWidget(self.market_box)

        self.board_box = QComboBox()
        self.board_box.addItem("全部板块")
        self.board_box.currentTextChanged.connect(self._filter)
        top.addWidget(self.board_box)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("搜索：代码(600519/AAPL) / 名称(茅台) / 拼音(gzmt)")
        self.search_input.textChanged.connect(self._filter)
        top.addWidget(self.search_input)

        self.ai_input = QLineEdit()
        self.ai_input.setPlaceholderText("AI搜索：如'帮我找贵州茅台'")
        self.ai_input.returnPressed.connect(self._ai_search)
        top.addWidget(self.ai_input)

        self.ai_btn = QPushButton("🤖 AI")
        self.ai_btn.clicked.connect(self._ai_search)
        top.addWidget(self.ai_btn)
        layout.addLayout(top)

        # 结构化筛选行：价格区间 / 涨跌幅区间 → 一键筛选
        flt = QHBoxLayout()
        flt.addWidget(QLabel("价格(元)"))
        self.sp_price_min = QDoubleSpinBox()
        self.sp_price_min.setRange(0, 1e7)
        self.sp_price_min.setSpecialValueText("不限")
        self.sp_price_min.setMaximumWidth(90)
        flt.addWidget(self.sp_price_min)
        flt.addWidget(QLabel("~"))
        self.sp_price_max = QDoubleSpinBox()
        self.sp_price_max.setRange(0, 1e7)
        self.sp_price_max.setSpecialValueText("不限")
        self.sp_price_max.setMaximumWidth(90)
        flt.addWidget(self.sp_price_max)
        flt.addWidget(QLabel("涨跌幅%"))
        self.sp_chg_min = QDoubleSpinBox()
        self.sp_chg_min.setRange(-100, 100)
        self.sp_chg_min.setSpecialValueText("不限")
        self.sp_chg_min.setMaximumWidth(80)
        flt.addWidget(self.sp_chg_min)
        flt.addWidget(QLabel("~"))
        self.sp_chg_max = QDoubleSpinBox()
        self.sp_chg_max.setRange(-100, 100)
        self.sp_chg_max.setSpecialValueText("不限")
        self.sp_chg_max.setMaximumWidth(80)
        flt.addWidget(self.sp_chg_max)
        self.btn_screener = QPushButton("🔍 结构化筛选")
        self.btn_screener.setToolTip(
            "按市场/板块 + 价格区间 + 涨跌幅区间筛选（A股实时，港股美股代码级）")
        self.btn_screener.clicked.connect(self._run_screener)
        flt.addWidget(self.btn_screener)
        flt.addStretch(1)
        layout.addLayout(flt)

        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels(
            ["代码", "名称", "现价", "涨跌幅%", "板块", "市场", "操作"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.doubleClicked.connect(self._on_double_click)
        self.table.setSortingEnabled(True)
        layout.addWidget(self.table)

        self.status = QLabel("")
        layout.addWidget(self.status)

    def _init_stocks(self):
        self._stocks = _load_all_stocks()
        # 加拼音字段
        for s in self._stocks:
            s["pinyin"] = stock_index.get_pinyin_abbr(s["name"])
        boards = sorted(set(s.get("board", "未知") for s in self._stocks))
        for b in boards:
            self.board_box.addItem(b)
        self.status.setText(f"共 {len(self._stocks)} 只股票，支持代码/名称/拼音搜索，双击复制")
        self._show_all()

    def _show_all(self):
        self.table.setSortingEnabled(False)
        self.table.setRowCount(min(len(self._stocks), 500))
        for i, s in enumerate(self._stocks[:500]):
            self._fill_row(i, s)
        self.table.setSortingEnabled(True)

    def _fill_row(self, row: int, s: dict):
        self.table.setItem(row, 0, QTableWidgetItem(s["code"]))
        self.table.setItem(row, 1, QTableWidgetItem(s["name"]))
        price = s.get("price")
        chg = s.get("chg_pct")
        self.table.setItem(row, 2, QTableWidgetItem(
            f"{price:.2f}" if price is not None else "—"))
        item_chg = QTableWidgetItem(
            f"{chg:+.2f}" if chg is not None else "—")
        if chg is not None:
            from PyQt6.QtGui import QColor
            item_chg.setForeground(QColor("#c0392b" if chg >= 0 else "#1e8449"))
        self.table.setItem(row, 3, item_chg)
        self.table.setItem(row, 4, QTableWidgetItem(s.get("board", "")))
        self.table.setItem(row, 5, QTableWidgetItem(s.get("market", "")))
        btn = QPushButton("加入自选")
        btn.clicked.connect(lambda _=False, c=s["ticker"]: self._join_watch(c))
        self.table.setCellWidget(row, 6, btn)

    def _filter(self, *_):
        board = self.board_box.currentText()
        market = self.market_box.currentText()
        text = self.search_input.text().strip().lower()
        results = []
        for s in self._stocks:
            if board != "全部板块" and s.get("board") != board:
                continue
            if market != "全部市场" and s.get("market", "") != market:
                continue
            if not text:
                results.append(s)
                continue
            code = s["code"].lower()
            name = s["name"].lower()
            pinyin = s.get("pinyin", "").lower()
            if (text in code or text in name or
                    (pinyin and pinyin.startswith(text) and len(text) >= 2)):
                results.append(s)
        show = results[:500]
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(show))
        for i, s in enumerate(show):
            self._fill_row(i, s)
        self.table.setSortingEnabled(True)
        self.status.setText(f"找到 {len(results)} 只（显示前{len(show)}只）")

    def _copy(self, code: str):
        from PyQt6.QtWidgets import QApplication
        QApplication.clipboard().setText(code)
        self.status.setText(f"已复制: {code}")

    def _join_watch(self, ticker: str):
        self.add_watchlist.emit(ticker)
        self.status.setText(f"已请求加入自选: {ticker}")

    def _on_double_click(self):
        row = self.table.currentRow()
        if row >= 0:
            item = self.table.item(row, 0)
            if item:
                self._join_watch(item.text())

    def _run_screener(self):
        if getattr(self, "_sw", None) and self._sw.isRunning():
            self.status.setText("筛选进行中…")
            return
        market = "全部" if self.market_box.currentText() == "全部市场" \
            else self.market_box.currentText()
        board = None if self.board_box.currentText() == "全部板块" \
            else self.board_box.currentText()
        cond = {
            "market": market, "board": board,
            "price_min": None if self.sp_price_min.value() == 0
            else self.sp_price_min.value(),
            "price_max": None if self.sp_price_max.value() == 0
            else self.sp_price_max.value(),
            "chg_min": None if self.sp_chg_min.value() == 0
            else self.sp_chg_min.value(),
            "chg_max": None if self.sp_chg_max.value() == 0
            else self.sp_chg_max.value(),
            "limit": 50,
        }
        self.status.setText("结构化筛选中（A股实时快照）…")
        self.btn_screener.setEnabled(False)
        self._sw = _ScreenerWorker(cond)
        self._sw.done.connect(self._on_screener_done)
        self._sw.failed.connect(self._on_screener_failed)
        self._sw.start()

    def _on_screener_done(self, hits: list, note: str):
        self.btn_screener.setEnabled(True)
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(hits))
        for i, s in enumerate(hits):
            self._fill_row(i, s)
        self.table.setSortingEnabled(True)
        self.status.setText(f"筛选到 {len(hits)} 只 · {note}")

    def _on_screener_failed(self, err: str):
        self.btn_screener.setEnabled(True)
        self.status.setText(f"筛选失败：{err}")

    def _copy_code(self):
        row = self.table.currentRow()
        if row >= 0:
            code_item = self.table.item(row, 0)
            if code_item:
                self._copy(code_item.text())

    def _ai_search(self):
        query = self.ai_input.text().strip()
        if not query:
            return
        self.status.setText("AI搜索中…")
        self.ai_worker = _AISearchWorker(query)
        self.ai_worker.done.connect(self._on_ai_done)
        self.ai_worker.failed.connect(self._on_ai_failed)
        self.ai_worker.start()

    def _on_ai_done(self, code: str):
        self.search_input.setText(code)
        self.status.setText(f"AI找到: {code}")

    def _on_ai_failed(self, err: str):
        self.status.setText(f"AI搜索失败: {err}")