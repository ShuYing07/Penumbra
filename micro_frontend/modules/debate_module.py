# -*- coding: utf-8 -*-
"""微前端模块：多空辩论模块。"""
from __future__ import annotations


class DebateModule:
    name = "debate"
    label = "多空辩论"

    def __init__(self):
        self._mounted = False
        self._handle = None

    def mount(self, ctx, container=None):
        self._mounted = True
        self._handle = {"ctx": ctx, "container": container, "rounds": []}
        ctx.bus.emit("debate:mounted", {"name": self.name})
        return self._handle

    def unmount(self):
        self._mounted = False
        self._handle = None

    def ping(self) -> bool:
        return self._mounted

    def start(self, ticker: str) -> dict:
        """发起辩论（协议入口；宿主接入 Claim-level 对抗引擎）。"""
        if not self._mounted:
            return {"ok": False, "error": "模块未挂载"}
        return {"ok": True, "ticker": ticker, "status": "started"}
