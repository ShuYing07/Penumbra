# -*- coding: utf-8 -*-
"""AI 信号历史回放。

- store：回放信号独立表 ai_replay_signals（与真实 decisions 物理隔离）
- engine：历史选点 → 时点切片跑分析管线 → t+N 真实走势评估 → 命中率统计
"""
from __future__ import annotations

from core.replay import store


def init() -> None:
    """建表（幂等）。"""
    store.init()
