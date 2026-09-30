# -*- coding: utf-8 -*-
"""多图表同步事件总线（模块六 · 参考 VNInvestCharts 六路同步）。

轻量观察者总线：跨标签页/图表同步十字光标索引、可见区间、时间锚。
无 GUI 依赖（纯 Python 可测）；PyQt 侧通过桥接类注册回调。

- SyncBus：单例主题总线，subscribe(topic, cb) / publish(topic, payload)；
- TOPICS：cursor（十字光标）、range（可见区间）、anchor（时间锚）、
  playback（回放进度）。
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Dict, List

log = logging.getLogger("stockai.core.chart_sync")

TOPIC_CURSOR = "cursor"
TOPIC_RANGE = "range"
TOPIC_ANCHOR = "anchor"
TOPIC_PLAYBACK = "playback"
ALL_TOPICS = (TOPIC_CURSOR, TOPIC_RANGE, TOPIC_ANCHOR, TOPIC_PLAYBACK)


class SyncBus:
    """进程内主题总线（线程安全）。"""

    _instance: "SyncBus | None" = None
    _lock = threading.Lock()

    def __new__(cls) -> "SyncBus":
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._subs: Dict[str, List[Callable]] = {}
                cls._instance._last: Dict[str, Any] = {}
            return cls._instance

    def subscribe(self, topic: str, cb: Callable[[Any], None]) -> None:
        if topic not in ALL_TOPICS:
            log.debug("未知主题：%s", topic)
            return
        with self._lock:
            self._subs.setdefault(topic, []).append(cb)

    def unsubscribe(self, topic: str, cb: Callable[[Any], None]) -> None:
        with self._lock:
            subs = self._subs.get(topic, [])
            if cb in subs:
                subs.remove(cb)

    def publish(self, topic: str, payload: Any) -> int:
        """广播；返回收到回调数。保存 last 供后订阅者取快照。"""
        with self._lock:
            self._last[topic] = payload
            subs = list(self._subs.get(topic, []))
        n = 0
        for cb in subs:
            try:
                cb(payload)
                n += 1
            except Exception as e:  # noqa: BLE001
                log.debug("同步回调失败：%s", e)
        return n

    def last(self, topic: str) -> Any:
        with self._lock:
            return self._last.get(topic)


# 便捷函数（进程内共享同一单例）
def sync_publish(topic: str, payload: Any) -> int:
    return SyncBus().publish(topic, payload)


def sync_subscribe(topic: str, cb: Callable[[Any], None]) -> None:
    SyncBus().subscribe(topic, cb)


if __name__ == "__main__":
    bus = SyncBus()
    got: list = []
    bus.subscribe(TOPIC_CURSOR, lambda p: got.append(p))
    n = bus.publish(TOPIC_CURSOR, {"i": 42, "price": 320.5})
    assert n == 1 and got == [{"i": 42, "price": 320.5}]
    assert bus.last(TOPIC_CURSOR) == {"i": 42, "price": 320.5}
    # 双实例同单例
    assert SyncBus() is bus
    # 未知主题静默
    assert bus.publish("nope", 1) == 0
    print("chart_sync self-check ok (single instance, "
          f"callbacks={n}, last={bus.last(TOPIC_CURSOR)})")
