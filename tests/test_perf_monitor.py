# -*- coding: utf-8 -*-
"""任务书A·模块三：性能监控测试。"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("STOCKAI_MOCK", "1")

import time
from core.performance_monitor import PerformanceMonitor, perf, _rss_mb

# 1) 计时
m = PerformanceMonitor()
h = m.start_timer("test_mod")
time.sleep(0.05)
ms = m.stop_timer("test_mod", h)
assert ms > 30 and m.get_snapshot()["modules"]["test_mod"]["calls"] == 1
# with 上下文
with m.timed("test_ctx"):
    time.sleep(0.02)
assert m.get_snapshot()["modules"]["test_ctx"]["calls"] == 1
assert m.get_snapshot()["modules"]["test_ctx"]["last_ms"] > 10
print("[ok] 计时器:", round(ms, 1), "ms / ctx")

# 2) API 计数
m.record_api("get_daily", 3)
assert m.api_count("get_daily") == 3
sn = m.get_snapshot()
assert sn["api_calls"]["get_daily"] == 3
print("[ok] API 计数")

# 3) 内存采样（Windows ctypes 可用返回数值）
mb = _rss_mb()
assert mb is None or mb > 0
print("[ok] 内存采样:", mb)

# 4) 异常检查（无异常时空列表）
an = m.check_anomalies()
assert isinstance(an, list)
print("[ok] 异常检查:", an or "无异常")

# 5) 全局单例
assert perf is not None and hasattr(perf, "record_api")
print("[ok] 全局单例")

print("\nALL PASS")
