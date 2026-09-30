# -*- coding: utf-8 -*-
"""数据总线（模块一 · 数据层与 Agent 层解耦）。

参考 TradingAgents / ark-market-data-mcp 的设计主张：生产级 AI 交易系统的
数据中枢不应依赖 HTTP 短连接。本模块提供一个进程内事件总线：

- RealtimeEngine（core/realtime_engine.py）把行情推送进 DataBus；
- Agent 工具层（agent/tool_defs.py）优先从 DataBus 读取最新快照，不直接
  轮询 HTTP；无快照时降级到 core.data.service 拉取（保持离线可用）。

职责边界：
- DataBus 只做「订阅 / 发布 / 最新快照」三件事，不做行情清洗；
- 所有读写加锁，线程安全（RealtimeEngine 工作线程 ↔ Agent 调用线程）；
- 订阅者不感知数据源是 WebSocket 还是轮询——由 RealtimeEngine 决定。
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Dict, List, Optional

log = logging.getLogger("stockai.databus")

_MAX_SNAPSHOTS = 256          # 快照保留上限（防止内存无限增长）
_STALE_MS = 30_000            # 快照超过 30s 视为过期（读侧标注 stale）


class DataBus:
    """进程内行情数据总线：最新快照 + 订阅者回调 + 一次性拉取。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._snapshots: Dict[str, dict] = {}   # code -> {ts, data}
        self._subs: Dict[str, List[Callable[[str, dict], None]]] = {}
        self._order: List[str] = []             # 快照插入序（LRU 淘汰）

    # ---------------- 发布侧（RealtimeEngine 调用） ----------------
    def publish(self, code: str, data: dict) -> None:
        """推送一条行情快照。code 归一化为大写。"""
        code = code.upper()
        with self._lock:
            if code not in self._snapshots:
                self._order.append(code)
            self._snapshots[code] = {"ts": time.time(), "data": data}
            while len(self._order) > _MAX_SNAPSHOTS:
                drop = self._order.pop(0)
                self._snapshots.pop(drop, None)
            subs = list(self._subs.get(code, []))
        for fn in subs:
            try:
                fn(code, data)
            except Exception as e:  # noqa: BLE001
                log.debug("订阅回调失败 %s: %s", code, e)

    # ---------------- 订阅侧（Agent / UI 调用） ----------------
    def subscribe(self, code: str, fn: Callable[[str, dict], None]) -> None:
        code = code.upper()
        with self._lock:
            self._subs.setdefault(code, []).append(fn)

    def unsubscribe(self, code: str, fn: Callable[[str, dict], None]) -> None:
        code = code.upper()
        with self._lock:
            subs = self._subs.get(code, [])
            if fn in subs:
                subs.remove(fn)
            if not subs:
                self._subs.pop(code, None)

    # ---------------- 读取侧 ----------------
    def latest(self, code: str, max_stale_ms: int = _STALE_MS) -> dict:
        """读取最新快照。返回 {ok, data, ts, age_ms, stale}。"""
        code = code.upper()
        with self._lock:
            snap = self._snapshots.get(code)
        if snap is None:
            return {"ok": False, "data": None, "ts": None, "age_ms": None,
                    "stale": True, "reason": "总线无此标的最新快照"}
        age_ms = (time.time() - snap["ts"]) * 1000
        return {"ok": True, "data": snap["data"], "ts": snap["ts"],
                "age_ms": round(age_ms, 1), "stale": age_ms > max_stale_ms}

    def codes(self) -> List[str]:
        with self._lock:
            return list(self._order)

    def stats(self) -> dict:
        with self._lock:
            return {"snapshots": len(self._snapshots), "subs": sum(
                len(v) for v in self._subs.values())}


# 进程级单例（UI 与 RealtimeEngine 共享同一总线）
_bus: Optional[DataBus] = None
_bus_lock = threading.Lock()


def get_bus() -> DataBus:
    global _bus
    with _bus_lock:
        if _bus is None:
            _bus = DataBus()
        return _bus


def reset_bus() -> DataBus:
    """重建单例（测试隔离用）。"""
    global _bus
    with _bus_lock:
        _bus = DataBus()
        return _bus


def bus_latest(code: str) -> dict:
    """便捷入口：优先总线快照；stale/缺失由调用方决定是否降级 HTTP。"""
    return get_bus().latest(code)


if __name__ == "__main__":
    # 自检：发布 → 订阅回调 → 最新快照 → 过期标注
    b = reset_bus()
    got: list = []

    def _cb(code: str, data: dict) -> None:
        got.append((code, data.get("close")))

    b.subscribe("600519", _cb)
    b.publish("600519", {"close": 1500.0, "chg_pct": 1.2})
    assert b.latest("600519")["ok"] is True
    assert ("600519", 1500.0) in got, "订阅回调未触发"
    assert b.latest("AAPL")["ok"] is False, "未知标的应返回 ok=False"
    print("data_bus self-check ok,", b.stats())
