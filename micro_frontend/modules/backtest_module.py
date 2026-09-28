# -*- coding: utf-8 -*-
"""微前端模块：回测模块。"""
from __future__ import annotations


class BacktestModule:
    name = "backtest"
    label = "策略回测"

    def __init__(self):
        self._mounted = False
        self._handle = None

    def mount(self, ctx, container=None):
        self._mounted = True
        self._handle = {"ctx": ctx, "container": container, "runs": []}
        ctx.bus.emit("backtest:mounted", {"name": self.name})
        return self._handle

    def unmount(self):
        self._mounted = False
        self._handle = None

    def ping(self) -> bool:
        return self._mounted

    def run(self, ticker: str, strategy: str = "rsi_rebound") -> dict:
        if not self._mounted:
            return {"ok": False, "error": "模块未挂载"}
        return {"ok": True, "ticker": ticker, "strategy": strategy, "status": "queued"}
