# -*- coding: utf-8 -*-
"""模块七：AI 推理可观测性测试。"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("STOCKAI_MOCK", "1")

from agent.agent_events import EventType, AgentEvent, EventCollector, event_label
from agent.agent_trace_store import save_trace, get_trace, init, list_analysis_ids

# 1) 事件定义与标签
assert EventType.THINKING.value == "thinking"
assert event_label(EventType.TOOL_CALL) == "🔧 调用工具"
print("[ok] 事件类型/标签")

# 2) EventCollector：收集 + 回调
seen = []
col = EventCollector()
col.set_callback(lambda ev: seen.append(ev))
col.emit(EventType.THINKING, "规划 2 步")
col.emit(EventType.TOOL_CALL, "调用 fetch_stock_data", tool="fetch_stock_data")
assert len(col.events) == 2 and len(seen) == 2
assert seen[0].event_type == EventType.THINKING
snap = col.snapshot()
assert snap[1]["metadata"]["tool"] == "fetch_stock_data"
print("[ok] EventCollector:", len(snap), "事件")

# 3) trace 持久化（SQLite）
init()
import time
_ts = time.time()
aid = "test-trace-001"
n = save_trace(aid, [
    {"event_type": "thinking", "content": "规划", "timestamp": _ts, "metadata": {}},
    {"event_type": "tool_call", "content": "调用", "timestamp": _ts + 0.1,
     "metadata": {"tool": "fetch_stock_data"}},
])
assert n == 2, n
tr = get_trace(aid)
assert len(tr) == 2 and tr[0]["event_type"] == "thinking"
# 幂等：重复保存先清理
n2 = save_trace(aid, [{"event_type": "final_report", "content": "ok",
                       "timestamp": _ts + 0.2, "metadata": {}}])
assert n2 == 1 and len(get_trace(aid)) == 1
assert aid in list_analysis_ids(10)
print("[ok] trace 持久化/幂等/查询")

# 4) AgentCore 事件注入（mock 环境跑完整 run）
from agent.agent_core import AgentCore
core = AgentCore()
got = []
core.set_event_callback(lambda ev: got.append(ev))
res = core.run("分析一下茅台")
assert res.get("events") and len(res["events"]) >= 4, res.get("events")
types = [e["event_type"] for e in res["events"]]
assert types[0] == "thinking" and types[-1] == "final_report", types
assert any(t == "tool_call" for t in types) and any(t == "tool_result" for t in types)
assert len(got) == len(res["events"])  # 回调与收集一致
print("[ok] AgentCore 事件流:", " → ".join(types))

print("\nALL PASS")
