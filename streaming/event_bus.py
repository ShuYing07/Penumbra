# -*- coding: utf-8 -*-
"""实时流处理 · 事件总线：基于 asyncio 的发布-订阅。

事件类型：data_ingested / analysis_completed / alert_triggered / trade_executed。
支持多订阅者、背压（队列上限，满时丢弃并计数）、事件滞留时长。
"""
from __future__ import annotations

import asyncio
import time
import uuid
from collections import defaultdict


class EventBus:
    def __init__(self, max_queue: int = 1000):
        self._subs: dict[str, list[asyncio.Queue]] = defaultdict(list)
        self._max_queue = max_queue
        self.dropped = 0
        self.published = 0
        self._lock = asyncio.Lock()

    async def publish(self, event_type: str, payload: dict | None = None) -> str:
        """发布事件，返回 event_id。"""
        event = {"id": uuid.uuid4().hex[:12], "type": event_type,
                 "payload": payload or {}, "ts": time.time()}
        async with self._lock:
            self.published += 1
            for q in list(self._subs.get(event_type, [])):
                try:
                    q.put_nowait(event)
                except asyncio.QueueFull:
                    self.dropped += 1
        return event["id"]

    def subscribe(self, event_type: str, maxsize: int = 64) -> asyncio.Queue:
        q = asyncio.Queue(maxsize=maxsize)
        self._subs[event_type].append(q)
        return q

    def unsubscribe(self, event_type: str, q: asyncio.Queue) -> None:
        if q in self._subs.get(event_type, []):
            self._subs[event_type].remove(q)

    def pending(self) -> int:
        return sum(q.qsize() for qs in self._subs.values() for q in qs)

    def stats(self) -> dict:
        return {"published": self.published, "dropped": self.dropped,
                "pending": self.pending(),
                "subscribers": {k: len(v) for k, v in self._subs.items()}}


# 事件类型常量
DATA_INGESTED = "data_ingested"
ANALYSIS_COMPLETED = "analysis_completed"
ALERT_TRIGGERED = "alert_triggered"
TRADE_EXECUTED = "trade_executed"
