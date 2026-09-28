# -*- coding: utf-8 -*-
"""全局命令面板（Ctrl+K）：搜索 功能 / 股票 / 历史分析 并直接跳转。

设计参考 OpenTerminal 的 ⌘K 全局命令面板：
- 输入即过滤（不区分大小写，支持拼音缩写/别名由股票索引提供）；
- 上下键选择、回车执行、Esc 关闭；
- 分组展示：功能 / 股票 / 历史记录。
"""
from __future__ import annotations

import json
import logging
import os

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QLineEdit,
                             QListWidget, QListWidgetItem, QVBoxLayout)

log = logging.getLogger("stockai.ui.command_palette")

# 拼音缩写匹配（可选）：安装 pypinyin 后启用，如 gzmt → 贵州茅台
try:
    from pypinyin import lazy_pinyin  # type: ignore
    _PYIN = True
except Exception:  # noqa: BLE001
    _PYIN = False


def _stock_index() -> list[dict]:
    """从本地 all_stocks.json 加载全量股票索引（失败返回空表）。"""
    try:
        p = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))), "data", "all_stocks.json")
        if not os.path.exists(p):
            return []
        with open(p, encoding="utf-8") as f:
            stocks = json.load(f)
        idx = []
        for s in stocks:
            alias = s.get("alias") or []
            idx.append({"code": s.get("code", ""), "name": s.get("name", ""),
                        "market": s.get("market", ""),
                        "alias": " ".join(alias) if isinstance(alias, list) else str(alias)})
        return idx
    except Exception as e:  # noqa: BLE001
        log.warning("命令面板股票索引加载失败: %s", e)
        return []


def _history_items(limit: int = 10) -> list[dict]:
    """最近分析历史（decision_logger），供快速回到之前的分析。"""
    try:
        from decision_logger import recent_decisions
        return [{"code": r.get("stock_code", ""), "name": r.get("stock_name", ""),
                 "ts": str(r.get("created_at", ""))[:10]}
                for r in recent_decisions(limit)]
    except Exception:  # noqa: BLE001
        return []


class CommandPaletteDialog(QDialog):
    """全局命令面板。execute(index, payload) 信号由主窗口处理。"""

    execute = pyqtSignal(int, object)  # action_type: 0=导航 1=股票 2=历史

    def __init__(self, nav_items: list[tuple[str, int]], parent=None):
        super().__init__(parent)
        self.setWindowTitle("全局命令面板  ·  Ctrl+K")
        self.setModal(True)
        self.resize(520, 420)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)

        self._nav = nav_items
        self._stocks = _stock_index()
        self._history = _history_items()
        self._rows: list[tuple[int, object]] = []  # (type, payload)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)

        self.edit = QLineEdit()
        self.edit.setPlaceholderText("搜索功能 / 股票代码 / 名称 / 拼音，如：回测、600519、gzmt、茅台")
        self.edit.textChanged.connect(self._filter)
        lay.addWidget(self.edit)

        self.list = QListWidget()
        lay.addWidget(self.list, 1)

        tip = QLabel("↑↓ 选择 · Enter 执行 · Esc 关闭")
        tip.setStyleSheet("color:#8B949E; font-size:11px;")
        lay.addWidget(tip)

        self.edit.returnPressed.connect(self._run_current)
        self.list.itemActivated.connect(lambda _it: self._run_current())

        # Esc 关闭（Frameless 下需手动绑定）
        QShortcut(QKeySequence("Esc"), self, activated=self.reject)

        self._filter("")
        self.edit.setFocus()

    # ---------- 过滤 ----------
    def _filter(self, text: str) -> None:
        t = text.strip().lower()
        self.list.clear()
        self._rows = []

        def push(kind: int, label: str, payload, hint: str = "") -> None:
            it = QListWidgetItem(f"{label}")
            if hint:
                it.setText(f"{label}　{hint}")
            self._rows.append((kind, payload))
            self.list.addItem(it)

        # 1) 功能导航
        for name, idx in self._nav:
            if not t or t in name.lower() or t in str(idx):
                push(0, f"⚡ {name}", idx)

        # 2) 股票（全量索引；空输入只展示少量、有输入时命中限 50 条防卡顿）
        stock_hits: list = []
        if t:
            # 拼音首字母缩写（仅安装 pypinyin 后启用）
            py_abbr: str | None = None
            if _PYIN:
                py_abbr = "".join(p[0] for p in lazy_pinyin(t) if p and p[0].isalpha())
            for s in self._stocks:
                hay = f"{s['code']} {s['name']} {s['market']} {s['alias']}".lower()
                if t in hay:
                    stock_hits.append(s)
                elif py_abbr and len(py_abbr) >= 2 and py_abbr in "".join(
                        p[0] for p in lazy_pinyin(s["name"]) if p and p[0].isalpha()):
                    stock_hits.append(s)
                if len(stock_hits) >= 50:
                    break
        else:
            stock_hits = self._stocks[:5]
        for s in stock_hits:
            push(1, f"📈 {s['name']}　{s['code']} ({s['market']})", s)

        # 3) 历史
        for h in self._history:
            if not t or t in f"{h.get('code','')} {h.get('name','')}".lower():
                push(2, f"🕘 {h.get('name','')}　{h.get('code','')}（{h.get('ts','')}）", h)

    # ---------- 键盘导航 ----------
    def keyPressEvent(self, e) -> None:  # noqa: N802
        if e.key() == Qt.Key.Key_Down:
            r = self.list.currentRow()
            self.list.setCurrentRow(min(r + 1, self.list.count() - 1))
            return
        if e.key() == Qt.Key.Key_Up:
            r = self.list.currentRow()
            self.list.setCurrentRow(max(r - 1, 0))
            return
        if e.key() == Qt.Key.Key_Escape:
            self.reject()
            return
        super().keyPressEvent(e)

    def _run_current(self) -> None:
        r = self.list.currentRow()
        if 0 <= r < len(self._rows):
            kind, payload = self._rows[r]
            self.execute.emit(kind, payload)
            self.accept()
