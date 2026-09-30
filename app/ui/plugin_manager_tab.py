# -*- coding: utf-8 -*-
"""插件管理标签页（模块五）：列表/启用禁用/卸载/zip 安装/权限确认。"""
from __future__ import annotations

import logging

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import (QAbstractItemView, QComboBox, QFileDialog,
                             QHBoxLayout, QLabel, QPushButton, QTableWidget,
                             QTableWidgetItem, QVBoxLayout, QWidget)

log = logging.getLogger("stockai.ui.pluginmanager")


class _Worker(QThread):
    done = pyqtSignal(dict)

    def __init__(self, action: str, payload: dict, parent=None):
        super().__init__(parent)
        self._action = action
        self._payload = payload

    def run(self):
        from plugin_system import PluginManager
        mgr = PluginManager("plugins")
        try:
            if self._action == "list":
                self.done.emit({"action": "list", "plugins": mgr.list_plugins()})
            elif self._action == "load":
                name = self._payload["name"]
                ok = mgr.load(name, PluginContextShim())
                self.done.emit({"action": "load", "name": name, "ok": ok,
                                "error": (mgr.list_plugins() and
                                          next((p["error"] for p in mgr.list_plugins()
                                                if p["name"] == name), None))})
            elif self._action == "unload":
                mgr.unload(self._payload["name"])
                self.done.emit({"action": "unload", "name": self._payload["name"]})
            elif self._action == "install":
                r = mgr.install_zip(self._payload["path"])
                self.done.emit({"action": "install", **r})
        except Exception as e:  # noqa: BLE001
            self.done.emit({"action": "error", "error": str(e)[:200]})


class PluginContextShim:
    """UI 场景下加载插件时使用的空上下文（工具注册暂不入 Agent 循环）。"""
    tools: dict = {}
    nav_items: list = []
    data_access: bool = True


class PluginManagerTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)

        top = QHBoxLayout()
        self.btn_refresh = QPushButton("刷新")
        self.btn_refresh.clicked.connect(self._refresh)
        top.addWidget(self.btn_refresh)
        self.btn_load = QPushButton("启用选中")
        self.btn_load.clicked.connect(lambda: self._act("load"))
        top.addWidget(self.btn_load)
        self.btn_unload = QPushButton("禁用选中")
        self.btn_unload.clicked.connect(lambda: self._act("unload"))
        top.addWidget(self.btn_unload)
        self.btn_install = QPushButton("从 zip 安装…")
        self.btn_install.clicked.connect(self._install)
        top.addWidget(self.btn_install)
        self.status = QLabel("")
        self.status.setStyleSheet("color:#8B949E")
        top.addWidget(self.status, 1)
        lay.addLayout(top)

        hint = QLabel("插件通过 manifest.json 声明权限（data_access / network / file_write / ui），"
                      "启用时按声明授权。工具注册后可由 Agent 调用。")
        hint.setStyleSheet("color:#6B7488")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["插件", "版本", "作者", "权限", "状态", "错误"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setColumnWidth(0, 160)
        self.table.setColumnWidth(4, 120)
        self.table.setColumnWidth(5, 240)
        lay.addWidget(self.table, 1)

        self._worker: _Worker | None = None
        self._refresh()

    def _refresh(self):
        self.status.setText("扫描中…")
        self._worker = _Worker("list", {}, self)
        self._worker.done.connect(self._on_done)
        self._worker.start()

    def _act(self, action: str):
        row = self.table.currentRow()
        if row < 0:
            self.status.setText("请先选择一个插件")
            return
        name = self.table.item(row, 0).text()
        self.status.setText(f"处理 {name}…")
        self._worker = _Worker(action, {"name": name}, self)
        self._worker.done.connect(self._on_done)
        self._worker.start()

    def _install(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择插件 zip", "",
                                              "Plugin Archive (*.zip)")
        if not path:
            return
        self.status.setText(f"安装 {path}…")
        self._worker = _Worker("install", {"path": path}, self)
        self._worker.done.connect(self._on_done)
        self._worker.start()

    def _on_done(self, payload: dict):
        self.status.setText("完成")
        if payload.get("action") == "error":
            self.status.setText(f"错误：{payload['error']}")
            return
        if payload.get("action") == "install":
            if payload.get("ok"):
                self.status.setText(f"已安装 {payload.get('name')}，"
                                    f"声明权限：{', '.join(payload.get('permissions') or []) or '无'}")
            else:
                self.status.setText(f"安装失败：{payload.get('error')}")
        self._refresh()

    def _render(self, plugins: list[dict]):
        self.table.setRowCount(0)
        for p in plugins:
            r = self.table.rowCount()
            self.table.insertRow(r)
            self.table.setItem(r, 0, QTableWidgetItem(p["name"]))
            self.table.setItem(r, 1, QTableWidgetItem(p["version"]))
            self.table.setItem(r, 2, QTableWidgetItem(p["author"]))
            self.table.setItem(r, 3, QTableWidgetItem(", ".join(p["permissions"]) or "无"))
            state = "✅ 已启用" if p.get("enabled") else "⏸ 未启用"
            self.table.setItem(r, 4, QTableWidgetItem(state))
            self.table.setItem(r, 5, QTableWidgetItem(p.get("error") or ""))
