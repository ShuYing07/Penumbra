# -*- coding: utf-8 -*-
"""Agent 推理轨迹时间线（模块七）：展示 THINKING/TOOL_CALL/… 事件流。

可嵌入任意分析面板；事件逐条追加，已完成步骤带 ✅，进行中显示加载动画。
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QLabel, QScrollArea, QVBoxLayout, QWidget)

from agent.agent_events import EventType, event_label

_STEP_ICON = {
    EventType.THINKING: "🧠",
    EventType.TOOL_CALL: "🔧",
    EventType.TOOL_RESULT: "📥",
    EventType.REASONING: "⚙️",
    EventType.FINAL_REPORT: "📄",
}


class AgentTraceViewer(QWidget):
    """只读事件流时间线（HTML 渲染，样式与主界面暗色主题一致）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self._label = QLabel("（暂无推理轨迹）")
        self._label.setWordWrap(True)
        self._label.setTextFormat(Qt.TextFormat.RichText)
        self._label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._label)
        lay.addWidget(scroll)

    def add_event(self, ev) -> None:
        """追加一条 AgentEvent（线程回调→主线程调用）。"""
        cur = self._label.text()
        if cur in ("", "（暂无推理轨迹）"):
            cur = ""
        icon = _STEP_ICON.get(ev.event_type, "•")
        color = {"thinking": "#00B4D8", "tool_call": "#FFA726",
                 "tool_result": "#8B949E", "reasoning": "#00B4D8",
                 "final_report": "#00C853"}.get(ev.event_type.value, "#DCE1EB")
        line = (f"<div style='color:{color};padding:2px 0;font-size:12px;'>"
                f"{icon} <b>{event_label(ev.event_type)}</b> "
                f"<span style='color:#8B949E'>{ev.content}</span></div>")
        self._label.setText(cur + line)

    def add_from_dict(self, d: dict) -> None:
        from agent.agent_events import AgentEvent
        try:
            self.add_event(AgentEvent(
                event_type=EventType(d.get("event_type")),
                content=d.get("content", ""),
                timestamp=d.get("timestamp", 0),
                metadata=d.get("metadata") or {}))
        except Exception:  # noqa: BLE001
            pass

    def clear(self) -> None:
        self._label.setText("（暂无推理轨迹）")

    def to_html(self) -> str:
        return self._label.text()
