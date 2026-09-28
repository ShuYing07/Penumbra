# -*- coding: utf-8 -*-
"""微前端模块：K线图模块。"""
from __future__ import annotations


class KLineModule:
    name = "kline"
    label = "K 线图"

    def __init__(self):
        self._mounted = False
        self._handle = None

    def mount(self, ctx, container=None):
        """挂载：container 为 QWidget 时返回其引用（由宿主填充图表）。"""
        self._mounted = True
        self._handle = {"ctx": ctx, "container": container, "ticker": None}
        ctx.bus.emit("kline:mounted", {"name": self.name})
        return self._handle

    def unmount(self):
        self._mounted = False
        self._handle = None

    def ping(self) -> bool:
        return self._mounted

    def load(self, ticker: str) -> dict:
        """加载 K 线（协议入口；宿主负责真正取数渲染）。"""
        if not self._mounted:
            return {"ok": False, "error": "模块未挂载"}
        self._handle["ticker"] = ticker
        return {"ok": True, "ticker": ticker}
