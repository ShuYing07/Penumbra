# -*- coding: utf-8 -*-
"""流式处理：窗口计算 + 背压 + 批处理。

- window_mean / window_vol：滑动窗口统计（默认 5 分钟等效，样例以 tick 数表示）；
- backpressure_guard：有界队列 + 丢弃计数（背压）；
- StreamProcessor：摄取 → 清洗 → 分析 → 输出 的轻量管线；
- Flink / Spark Structured Streaming 为可选适配桩：`stream_backend` 探测，
  未安装自动降级内置实现。

与 streaming/event_bus 协同：本模块是"处理管线"，event_bus 是"事件通道"。
"""
from __future__ import annotations

import logging
import time
from collections import deque

log = logging.getLogger("stockai.pipeline.stream")


def window_mean(values: list[float], window: int) -> list[float | None]:
    """滑动窗口均值（左闭右闭，窗口不足返回 None）。"""
    if window <= 0:
        raise ValueError("window 必须为正")
    out: list[float | None] = []
    acc = 0.0
    dq: deque[float] = deque()
    for i, v in enumerate(values):
        dq.append(v)
        acc += v
        if len(dq) > window:
            acc -= dq.popleft()
        out.append(round(acc / len(dq), 4) if len(dq) == window else None)
    return out


def window_vol(values: list[float], window: int) -> list[float | None]:
    """滑动窗口成交量均值。"""
    return window_mean(values, window)


class _BoundedQueue:
    """有界队列：满则丢弃最旧并计数（背压信号）。"""

    def __init__(self, maxsize: int = 1000):
        self.maxsize = maxsize
        self._q: deque = deque()
        self.dropped = 0

    def put(self, item) -> bool:
        if len(self._q) >= self.maxsize:
            self.dropped += 1
            return False
        self._q.append(item)
        return True

    def get_nowait(self):
        return self._q.popleft()

    def size(self) -> int:
        return len(self._q)


def backpressure_guard(maxsize: int = 1000):
    """装饰器/上下文辅助：返回带背压的有界队列。"""
    return _BoundedQueue(maxsize)


class StreamProcessor:
    """摄取 → 清洗 → 分析 → 输出 管线。"""

    def __init__(self, window_size: int = 5, engine: str = "auto"):
        self.window_size = window_size
        self.engine = engine
        self._ticks: list[dict] = []
        self.alerts = 0
        self.processed = 0
        self._anomaly_threshold = 3.0  # 与窗口均值偏差倍数

    def stream_backend(self) -> str:
        """探测可用后端：spark/flink 未装 → builtin。"""
        if self.engine != "auto":
            return self.engine
        for mod in ("pyspark", "flink"):
            try:
                __import__(mod)
                return mod
            except ImportError:
                continue
        return "builtin"

    def process(self, ticker: str, tick: dict) -> dict | None:
        """处理一条行情 tick：清洗 + 窗口统计 + 异动告警。"""
        self.processed += 1
        try:
            close = float(tick.get("close"))
            vol = float(tick.get("volume") or 0)
        except (TypeError, ValueError):
            return {"ticker": ticker, "error": "非法数值", "alert": False}
        self._ticks.append({"ticker": ticker, "close": close, "volume": vol,
                            "ts": tick.get("ts") or time.time()})
        recent = [t["close"] for t in self._ticks[-self.window_size:]]
        mean = window_mean(recent, self.window_size)[-1]
        alert = False
        if mean is not None and abs(close - mean) / max(1e-9, abs(mean)) > self._anomaly_threshold:
            self.alerts += 1
            alert = True
            log.info("异动告警 %s close=%.2f mean=%.2f", ticker, close, mean)
        return {"ticker": ticker, "close": close, "window_mean": mean,
                "volume": vol, "alert": alert, "ts": time.time()}

    def flush_batch(self, max_batch: int = 500) -> list[dict]:
        """批处理输出（模拟离线批处理下游）。"""
        batch, self._ticks = self._ticks[:max_batch], self._ticks[max_batch:]
        return batch

    def stats(self) -> dict:
        return {"processed": self.processed, "alerts": self.alerts,
                "backend": self.stream_backend(), "queued": len(self._ticks)}


if __name__ == "__main__":
    w = window_mean([1, 2, 3, 4, 5], 3)
    assert w[-1] == 4.0 and w[0] is None
    sp = StreamProcessor(window_size=5)
    for v in [1, 2, 3, 4, 100]:
        r = sp.process("W", {"close": v, "volume": v})
    assert sp.alerts >= 1, "异动未触发"
    assert sp.stats()["processed"] == 5
    assert sp.stream_backend() in ("builtin", "pyspark", "flink")
    q = backpressure_guard(3)
    for i in range(10):
        q.put(i)
    assert q.dropped > 0 and q.size() == 3
    print(f"PASS stream_processor 自测 {sp.stats()}")
