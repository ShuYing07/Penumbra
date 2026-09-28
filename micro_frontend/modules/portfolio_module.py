# -*- coding: utf-8 -*-
"""微前端模块：组合管理模块。"""
from __future__ import annotations


class PortfolioModule:
    name = "portfolio"
    label = "组合管理"

    def __init__(self):
        self._mounted = False
        self._handle = None

    def mount(self, ctx, container=None):
        self._mounted = True
        self._handle = {"ctx": ctx, "container": container, "positions": []}
        ctx.bus.emit("portfolio:mounted", {"name": self.name})
        return self._handle

    def unmount(self):
        self._mounted = False
        self._handle = None

    def ping(self) -> bool:
        return self._mounted

    def snapshot(self) -> dict:
        if not self._mounted:
            return {"ok": False, "error": "模块未挂载"}
        return {"ok": True, "positions": self._handle["positions"]}
