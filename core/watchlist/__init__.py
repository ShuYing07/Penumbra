# -*- coding: utf-8 -*-
"""自选股 + 一句话盯盘 + 桌面通知。

- store：自选股/盯盘条件持久化（SQLite，沿用 cache.get_conn）
- conditions：条件解析引擎（parse）+ 评估引擎（evaluate）
- engine：scan_all 调度核心（批量取数 + 算指标 + 逐条评估 + 错误隔离）
"""
from __future__ import annotations

from core.watchlist import store


def init() -> None:
    """建表（幂等）。"""
    store.init()
