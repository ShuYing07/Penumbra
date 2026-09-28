# -*- coding: utf-8 -*-
"""实时流处理 · 数据摄取：流式行情/新闻摄取 + 背压控制。

- ingest_row()：单行摄取，正常路径经事件总线广播 data_ingested；
- 背压：内部队列超上限时丢尾部并计数（防止内存爆炸），
  lag() 暴露处理延迟供监控。
"""
from __future__ import annotations

import asyncio
import time

from streaming.event_bus import EventBus, DATA_INGESTED

_BACKPRESSURE_LIMIT = 10_000


class DataIngestion:
    def __init__(self, bus: EventBus | None = None, limit: int = _BACKPRESSURE_LIMIT):
        self.bus = bus or EventBus()
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=limit)
        self.ingested = 0
        self.dropped = 0
        self._last_ts = 0.0

    async def ingest(self, source: str, kind: str, record: dict) -> bool:
        """摄取一条记录；背压满则丢弃（返回 False）。"""
        if self._queue.full():
            self.dropped += 1
            return False
        await self._queue.put({"source": source, "kind": kind, "record": record,
                               "ts": time.time()})
        return True

    async def flush_to_bus(self) -> int:
        """把队列中的记录批量发布为 data_ingested 事件。"""
        n = 0
        while not self._queue.empty():
            try:
                item = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            await self.bus.publish(DATA_INGESTED, item)
            self.ingested += 1
            self._last_ts = time.time()
            n += 1
        return n

    def lag_seconds(self) -> float:
        """最近一次处理与现在的时间差（秒）；0=空闲。"""
        if not self._last_ts:
            return 0.0
        return round(time.time() - self._last_ts, 3)

    def stats(self) -> dict:
        return {"ingested": self.ingested, "dropped": self.dropped,
                "queue_size": self._queue.qsize(), "lag_sec": self.lag_seconds()}
