# -*- coding: utf-8 -*-
"""AI 推理过程可观测性：事件定义与收集器（模块七）。

事件流让用户看到 Agent "正在做什么"（OpenBB SSE 流式架构的本地化实现）：
- THINKING：解析意图 / 规划工具链
- TOOL_CALL：决定调用某个工具（含参数摘要）
- TOOL_RESULT：工具返回（含数据摘要）
- REASONING：基于结果的推理中间态
- FINAL_REPORT：最终报告生成

AgentEvent 为纯数据类（无 Qt 依赖），可被 PyQt 信号 / API / MCP 复用。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, List, Optional


class EventType(str, Enum):
    THINKING = "thinking"          # 思考/规划
    TOOL_CALL = "tool_call"        # 决定调用工具
    TOOL_RESULT = "tool_result"    # 工具返回
    REASONING = "reasoning"        # 推理中间态
    FINAL_REPORT = "final_report"  # 最终报告


_EVENT_LABELS = {
    EventType.THINKING: "🧠 思考",
    EventType.TOOL_CALL: "🔧 调用工具",
    EventType.TOOL_RESULT: "📥 工具返回",
    EventType.REASONING: "⚙️ 推理",
    EventType.FINAL_REPORT: "📄 生成报告",
}


def event_label(etype: EventType) -> str:
    return _EVENT_LABELS.get(etype, str(etype))


@dataclass
class AgentEvent:
    event_type: EventType
    content: str
    timestamp: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "event_type": self.event_type.value,
            "content": self.content,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }


class EventCollector:
    """线程安全的事件收集器：本地留存 + 实时回调。"""

    def __init__(self, callback: Optional[Callable[[AgentEvent], None]] = None):
        self._events: List[AgentEvent] = []
        self._cb = callback

    def set_callback(self, cb: Optional[Callable[[AgentEvent], None]]) -> None:
        self._cb = cb

    def emit(self, etype: EventType, content: str, **meta: Any) -> AgentEvent:
        ev = AgentEvent(event_type=etype, content=content, metadata=meta)
        self._events.append(ev)
        if self._cb is not None:
            try:
                self._cb(ev)
            except Exception:  # noqa: BLE001
                pass  # 回调异常不影响 Agent 主流程
        return ev

    def snapshot(self) -> List[dict]:
        return [e.to_dict() for e in self._events]

    @property
    def events(self) -> List[AgentEvent]:
        return list(self._events)

    def clear(self) -> None:
        self._events.clear()
