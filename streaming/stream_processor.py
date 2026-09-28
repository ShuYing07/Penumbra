# -*- coding: utf-8 -*-
"""实时流处理 · 流处理器：摄取 → 清洗 → 分析 → 输出 + 窗口计算。

- 清洗：缺失值/类型修复；
- 分析：窗口聚合（如 5 分钟成交量均值）、异动阈值；
- 输出：把结果发布到 analysis_completed / alert_triggered 事件。
"""
from __future__ import annotations

import asyncio
import time
from collections import deque

from streaming.event_bus import EventBus, ANALYSIS_COMPLETED, ALERT_TRIGGERED


class StreamProcessor:
    def __init__(self, bus: EventBus | None = None):
        self.bus = bus or EventBus()
        self._windows: dict[str, deque] = {}
        self.processed = 0
        self.alerts = 0

    # ---------- 清洗 ----------
    def clean(self, record: dict) -> dict:
        out = dict(record)
        for k in ("open", "high", "low", "close", "volume"):
            if k in out:
                try:
                    out[k] = float(out[k])
                except (TypeError, ValueError):
                    out[k] = None
        return out

    # ---------- 窗口计算 ----------
    def window_stats(self, key: str, value: float | None, window: int = 5) -> dict | None:
        """滑动窗口聚合；窗口满后返回 {mean, min, max, last}。"""
        if value is None:
            return None
        dq = self._windows.setdefault(key, deque(maxlen=window))
        dq.append(value)
        if len(dq) < window:
            return None
        vals = list(dq)
        return {"mean": round(sum(vals) / len(vals), 4),
                "min": round(min(vals), 4), "max": round(max(vals), 4),
                "last": round(vals[-1], 4)}

    # ---------- 异动判定（历史统计口径，非预测）----------
    def detect_alert(self, key: str, stats: dict, spike_ratio: float = 2.0) -> bool:
        if stats is None:
            return False
        mean = stats["mean"]
        if mean == 0:
            return False
        return stats["last"] > mean * spike_ratio

    async def process(self, ticker: str, record: dict) -> list[str]:
        """处理一条行情记录，返回触发的事件 id 列表。"""
        rec = self.clean(record)
        events = []
        vol = rec.get("volume")
        st = self.window_stats(ticker, vol, window=5)
        self.processed += 1
        if st:
            result = {"ticker": ticker, "volume_window": st,
                      "ts": time.time()}
            eid = await self.bus.publish(ANALYSIS_COMPLETED,
                                         {"ticker": ticker, "result": result})
            events.append(eid)
            if self.detect_alert(ticker, st):
                self.alerts += 1
                aid = await self.bus.publish(
                    ALERT_TRIGGERED,
                    {"ticker": ticker, "reason": f"成交量骤增(末值>均值×{2.0})",
                     "window": st})
                events.append(aid)
        return events

    def stats(self) -> dict:
        return {"processed": self.processed, "alerts": self.alerts,
                "windows": {k: list(v) for k, v in self._windows.items()}}
