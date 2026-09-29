# -*- coding: utf-8 -*-
"""任务书B·模块五：执行控制台（三模式追踪）测试。"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("STOCKAI_MOCK", "1")

from agent.execution_console import ExecutionConsole
from agent.agent_events import EventType, AgentEvent

# 1) 三模式渲染
events = [
    {"event_type": "thinking", "content": "规划", "timestamp": 1.0, "metadata": {}},
    {"event_type": "tool_call", "content": "fetch_stock_data(SH600519)",
     "timestamp": 1.1, "metadata": {"tool": "fetch_stock_data"}},
    {"event_type": "tool_result", "content": "6012 行", "timestamp": 1.5, "metadata": {}},
    {"event_type": "reasoning", "content": "趋势向上", "timestamp": 1.6, "metadata": {}},
    {"event_type": "final_report", "content": "完成", "timestamp": 1.7, "metadata": {}},
]
con = ExecutionConsole("user")
u = con.render(events)
assert "执行进度" in u and "规划" in u
con.set_mode("expert")
e = con.render(events)
assert "工具调用详情" in e and "fetch_stock_data" in e
con.set_mode("dev")
d = con.render(events, analysis_id="nonexistent")
assert "Dev" in d
print("[ok] 三模式渲染")

# 2) 空事件安全
assert "尚无执行记录" in ExecutionConsole.render_user([])
print("[ok] 空事件安全")

# 3) stats：无记录返回 0
st = ExecutionConsole.stats("no-such-id")
assert st["total_tokens"] == 0 and st["cost_cny"] == 0.0
print("[ok] stats 空安全")

# 4) waterfall：无记录空
wf = ExecutionConsole.waterfall("no-such-id")
assert isinstance(wf, list)
print("[ok] waterfall 空安全")

# 5) 事件对象流式渲染（AgentEvent）
seen = []
col = None
from agent.agent_events import EventCollector
col = EventCollector()
ev = AgentEvent(EventType.TOOL_CALL, "调用指标",
                metadata={"tool": "calculate_indicators"})
col.emit(ev.event_type, ev.content, tool=ev.metadata.get("tool"))
snap = col.snapshot()
assert len(snap) == 1 and snap[0]["metadata"]["tool"] == "calculate_indicators"
print("[ok] 事件流接入")

print("\nALL PASS")
