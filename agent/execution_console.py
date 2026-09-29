# -*- coding: utf-8 -*-
"""AI 推理执行控制台（任务书B·模块五）。

参考 FinSight Execution Console 的三模式追踪：

- User 模式：简洁进度列表（“正在做什么”，打勾已完成）。
- Expert 模式：工具调用详情（工具名 / 参数 / 结果摘要 / 耗时）。
- Dev 模式：LLM token / 成本 / 延迟统计 + 并行瀑布图数据（按分组）。

数据来源：
- 实时：EventCollector（agent/agent_events.py）回调事件流。
- 持久化：agent_traces 表（agent/agent_trace_store.py）回溯历史分析；
  token/成本从 token_ledger 表读取。
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

from agent.agent_events import EventType

log = logging.getLogger("stockai.execution_console")

_MODES = ("user", "expert", "dev")
_EVENT_ICON = {
    EventType.THINKING: "💭", EventType.TOOL_CALL: "🔧",
    EventType.TOOL_RESULT: "📥", EventType.REASONING: "🧠",
    EventType.FINAL_REPORT: "✅",
}


class ExecutionConsole:
    """三模式推理追踪控制台。"""

    def __init__(self, mode: str = "user"):
        self.mode = mode if mode in _MODES else "user"
        self._collector = None

    def set_mode(self, mode: str) -> None:
        if mode in _MODES:
            self.mode = mode

    def attach(self, collector) -> None:
        """订阅 EventCollector（AgentCore.events）。"""
        self._collector = collector
        if collector is not None and not getattr(collector, "_console_cb", None):
            collector.set_callback(lambda ev: None)  # 保留现有回调链

    # ---------------- 渲染 ----------------
    def render(self, events: List[dict], analysis_id: Optional[str] = None) -> str:
        if self.mode == "user":
            return self.render_user(events)
        if self.mode == "expert":
            return self.render_expert(events)
        return self.render_dev(events, analysis_id=analysis_id)

    @staticmethod
    def render_user(events: List[dict]) -> str:
        lines = ["<div style='font-family:Microsoft YaHei,Segoe UI,sans-serif;color:#DCE1EB'>"]
        lines.append("<h4 style='color:#8B949E;'>AI 执行进度（User 模式）</h4>")
        if not events:
            lines.append("<p style='color:#8B949E;'>尚无执行记录</p>")
        for ev in events:
            et = ev.get("event_type")
            icon = _EVENT_ICON.get(EventType(et), "•") if isinstance(et, str) else "•"
            content = str(ev.get("content") or "")[:60]
            lines.append(f"<p style='margin:2px 0'>{icon} {content}</p>")
        lines.append("</div>")
        return "".join(lines)

    @staticmethod
    def render_expert(events: List[dict]) -> str:
        lines = ["<div style='font-family:Microsoft YaHei,Segoe UI,sans-serif;color:#DCE1EB'>",
                 "<h4 style='color:#8B949E;'>工具调用详情（Expert 模式）</h4>",
                 "<table style='border-collapse:collapse;width:100%'>",
                 "<tr><th style='border:1px solid #1E2530;padding:4px 8px;color:#8B949E'>步骤</th>"
                 "<th style='border:1px solid #1E2530;padding:4px 8px;color:#8B949E'>类型</th>"
                 "<th style='border:1px solid #1E2530;padding:4px 8px;color:#8B949E'>内容</th></tr>"]
        for i, ev in enumerate(events):
            et = ev.get("event_type", "")
            meta = ev.get("metadata") or {}
            tool = meta.get("tool", "")
            content = str(ev.get("content") or "")
            if ev.get("event_type") == "tool_call":
                content = f"调用 {tool}: {content[:80]}"
            lines.append(
                f"<tr><td style='border:1px solid #1E2530;padding:4px 8px'>{i}</td>"
                f"<td style='border:1px solid #1E2530;padding:4px 8px;color:#00B4D8'>{et}</td>"
                f"<td style='border:1px solid #1E2530;padding:4px 8px'>{content[:120]}</td></tr>")
        lines.append("</table></div>")
        return "".join(lines)

    def render_dev(self, events: List[dict], analysis_id: Optional[str] = None) -> str:
        """Dev 模式：事件流 + token/成本 + 并行瀑布。"""
        parts = [self.render_expert(events)]
        if analysis_id:
            st = self.stats(analysis_id)
            wf = self.waterfall(analysis_id)
            parts.append("<h4 style='color:#8B949E;'>LLM Token / 成本 / 延迟（Dev）</h4>")
            parts.append(f"<p>Token：prompt <b>{st['prompt_tokens']}</b> / "
                         f"completion <b>{st['completion_tokens']}</b> / "
                         f"总 <b>{st['total_tokens']}</b>；成本 <b>¥{st['cost_cny']}</b></p>")
            if wf:
                parts.append("<h4 style='color:#8B949E;'>并行瀑布（分组）</h4><ul>")
                for row in wf:
                    parts.append(
                        f"<li style='color:#8B949E'>{row['group']} 组：{row['keys']} — "
                        f"{row['step_count']} 步，窗口 {row['span_ms']}ms</li>")
                parts.append("</ul>")
        parts.append("<p style='color:#8B949E;font-size:12px'>Dev 模式：事件流来自 "
                     "agent_traces / token_ledger，供调试与可解释性审计。</p>")
        return "".join(parts)

    # ---------------- 持久化数据 ----------------
    @staticmethod
    def stats(analysis_id: str) -> Dict[str, int]:
        """从 token_ledger 汇总某分析的 token 与成本。"""
        try:
            from core.data.cache import get_conn
            with get_conn() as conn:
                rows = conn.execute(
                    "SELECT COALESCE(SUM(prompt_tokens),0), COALESCE(SUM(completion_tokens),0),"
                    " COALESCE(SUM(total_tokens),0), COALESCE(SUM(cost_cny),0)"
                    " FROM token_ledger WHERE node LIKE ?",
                    (analysis_id + "%",)).fetchone()
        except Exception:  # noqa: BLE001
            rows = (0, 0, 0, 0.0)
        return {"prompt_tokens": int(rows[0] or 0), "completion_tokens": int(rows[1] or 0),
                "total_tokens": int(rows[2] or 0), "cost_cny": round(float(rows[3] or 0), 4)}

    @staticmethod
    def waterfall(analysis_id: str) -> List[Dict[str, object]]:
        """从 agent_traces 构建分组瀑布（按 analyst_team 分组，仅统计耗时窗口）。"""
        try:
            from agent.agent_trace_store import get_trace
            from core.agents.analyst_team import ANALYST_DEFS
            events = get_trace(analysis_id)
        except Exception:  # noqa: BLE001
            return []
        group_map = {a["key"]: a["group"] for a in ANALYST_DEFS}
        group_map.update({"thinking": "core", "tool_call": "core", "tool_result": "core",
                          "reasoning": "core", "final_report": "core",
                          "bull": "debate", "bear": "debate", "trader": "debate",
                          "risk": "risk", "leader": "leader"})
        groups: Dict[str, Dict[str, object]] = {}
        prev_ts = None
        for ev in events:
            ts = float(ev.get("timestamp") or 0)
            key = str(ev.get("metadata") or {}).get("node", "") or ev.get("event_type", "")
            g = group_map.get(key, "other")
            gd = groups.setdefault(g, {"keys": set(), "step_count": 0, "span_ms": 0.0,
                                       "t0": ts, "t1": ts})
            gd["keys"].add(key)
            gd["step_count"] += 1
            gd["t0"] = min(gd["t0"], ts)
            gd["t1"] = max(gd["t1"], ts)
            prev_ts = ts
        out = []
        for g, d in sorted(groups.items()):
            out.append({"group": g, "keys": sorted(d["keys"]),
                        "step_count": d["step_count"],
                        "span_ms": round((d["t1"] - d["t0"]) * 1000, 1)})
        return out
