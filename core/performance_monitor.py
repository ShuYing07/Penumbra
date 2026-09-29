# -*- coding: utf-8 -*-
"""运行时性能监控（任务书A·模块三）。

- 模块加载计时：start_timer/stop_timer 或 with timer("key") 记录各模块耗时
  （调用次数 / 累计 / 最近 / 最大，便于发现慢模块）。
- API 调用统计：record_api(name) 计数（数据源请求次数）。
- 内存采样：record_memory() 用 ctypes 读取本进程 RSS（Windows；非 Windows 返回 None）。
- 异常检查：check_anomalies() 按阈值提示（启动>20s、单模块>5s、内存>1.2GB）。

全局单例 perf = PerformanceMonitor()，任何层可直接 import 使用。
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Callable, Dict, List, Optional

log = logging.getLogger("stockai.perf")

_STARTUP_WARN_S = 20.0
_MODULE_WARN_MS = 5000.0
_MEM_WARN_MB = 1200.0


def _rss_mb() -> Optional[float]:
    """当前进程常驻内存 MB（Windows 用 ctypes；其他平台尽力而为）。"""
    try:
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes

            class _PMC(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD),
                    ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ]

            pmc = _PMC()
            pmc.cb = ctypes.sizeof(_PMC)
            if ctypes.windll.psapi.GetProcessMemoryInfo(
                    ctypes.windll.kernel32.GetCurrentProcess(),
                    ctypes.byref(pmc), pmc.cb):
                return round(pmc.WorkingSetSize / 1024 / 1024, 1)
            return None
        # 非 Windows：/proc/self/statm 尽力而为
        with open("/proc/self/statm", encoding="utf-8") as f:
            parts = f.read().split()
            if len(parts) >= 2:
                return round(int(parts[1]) * os.sysconf("SC_PAGE_SIZE") / 1024 / 1024, 1)
        return None
    except Exception:  # noqa: BLE001
        return None


class PerformanceMonitor:
    def __init__(self) -> None:
        self._started = time.time()
        self._modules: Dict[str, Dict[str, float]] = {}
        self._api: Dict[str, int] = {}
        self._mem_samples: List[Dict[str, float]] = []
        self._lock = threading.Lock()

    # ---------------- 计时 ----------------
    def start_timer(self, key: str) -> float:
        """返回一个句柄（单调时钟起点）。"""
        return time.monotonic()

    def stop_timer(self, key: str, handle: float) -> float:
        ms = (time.monotonic() - handle) * 1000.0
        with self._lock:
            m = self._modules.setdefault(key, {"calls": 0, "total_ms": 0.0,
                                               "last_ms": 0.0, "max_ms": 0.0})
            m["calls"] += 1
            m["total_ms"] += ms
            m["last_ms"] = ms
            m["max_ms"] = max(m["max_ms"], ms)
        return ms

    def timed(self, key: str):
        """with perf.timed('chart.load'): ..."""
        _lock = self._lock
        _modules = self._modules

        class _Ctx:
            def __enter__(self):
                self._h = time.monotonic()
                return self

            def __exit__(self, *exc):
                self._ms = (time.monotonic() - self._h) * 1000.0
                with _lock:
                    m = _modules.setdefault(key, {"calls": 0, "total_ms": 0.0,
                                                  "last_ms": 0.0, "max_ms": 0.0})
                    m["calls"] += 1
                    m["total_ms"] += self._ms
                    m["last_ms"] = self._ms
                    m["max_ms"] = max(m["max_ms"], self._ms)
                return False
        return _Ctx()

    # ---------------- API 计数 ----------------
    def record_api(self, name: str, n: int = 1) -> None:
        with self._lock:
            self._api[name] = self._api.get(name, 0) + int(n)

    def api_count(self, name: str) -> int:
        with self._lock:
            return self._api.get(name, 0)

    # ---------------- 内存 ----------------
    def record_memory(self) -> Optional[float]:
        mb = _rss_mb()
        if mb is not None:
            with self._lock:
                self._mem_samples.append({"t": time.time(), "mb": mb})
                if len(self._mem_samples) > 500:
                    self._mem_samples = self._mem_samples[-250:]
        return mb

    def memory_now(self) -> Optional[float]:
        return _rss_mb()

    # ---------------- 快照与异常 ----------------
    def get_snapshot(self) -> Dict[str, object]:
        with self._lock:
            modules = {k: dict(v) for k, v in self._modules.items()}
            api = dict(self._api)
        uptime = time.time() - self._started
        mem = _rss_mb()
        return {
            "uptime_s": round(uptime, 1),
            "memory_mb": mem,
            "modules": modules,
            "api_calls": api,
            "startup_ms": round(modules.get("startup", {}).get("last_ms", 0.0), 1),
        }

    def check_anomalies(self) -> List[str]:
        out: List[str] = []
        sn = self.get_snapshot()
        if sn["uptime_s"] < _STARTUP_WARN_S:
            pass  # 启动中不做判定
        elif sn["startup_ms"] > _STARTUP_WARN_S * 1000:
            out.append(f"启动耗时 {sn['startup_ms'] / 1000:.1f}s（>20s）")
        for k, m in sn["modules"].items():
            if m["last_ms"] > _MODULE_WARN_MS:
                out.append(f"模块 {k} 最近加载 {m['last_ms'] / 1000:.1f}s（>5s）")
        if sn["memory_mb"] and sn["memory_mb"] > _MEM_WARN_MB:
            out.append(f"内存占用 {sn['memory_mb']}MB（>1.2GB）")
        return out


perf = PerformanceMonitor()
