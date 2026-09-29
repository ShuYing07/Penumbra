# -*- coding: utf-8 -*-
"""Agent 推理轨迹持久化（模块七）。

将每次分析的完整事件流存入 SQLite（表 agent_traces），
支持按 analysis_id 回溯 Agent 的完整推理路径（可解释性账本）。
"""
from __future__ import annotations

import logging
from typing import List, Optional

from core.data.cache import get_conn

log = logging.getLogger("stockai.agent_trace")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_traces(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  analysis_id TEXT,
  step_index INTEGER,
  event_type TEXT,
  content TEXT,
  timestamp REAL,
  metadata TEXT
);
CREATE INDEX IF NOT EXISTS idx_traces_aid ON agent_traces(analysis_id);
"""


def init() -> None:
    with get_conn() as conn:
        conn.executescript(_SCHEMA)


def save_trace(analysis_id: str, events: List[dict]) -> int:
    """保存一次分析的完整事件流（幂等：同一 analysis_id 重复调用先清理旧轨迹）。"""
    if not events:
        return 0
    init()
    import json
    with get_conn() as conn:
        conn.execute("DELETE FROM agent_traces WHERE analysis_id=?", (analysis_id,))
        rows = [
            (analysis_id, i, e.get("event_type", ""), e.get("content", ""),
             float(e.get("timestamp", 0)),
             json.dumps(e.get("metadata", {}), ensure_ascii=False))
            for i, e in enumerate(events)
        ]
        conn.executemany(
            "INSERT INTO agent_traces(analysis_id, step_index, event_type,"
            " content, timestamp, metadata) VALUES (?,?,?,?,?,?)", rows)
        return len(rows)


def get_trace(analysis_id: str) -> List[dict]:
    """按 analysis_id 返回完整推理轨迹（按 step 排序）。"""
    init()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT step_index, event_type, content, timestamp, metadata"
            " FROM agent_traces WHERE analysis_id=? ORDER BY step_index", (analysis_id,)).fetchall()
    return [{"step_index": r[0], "event_type": r[1], "content": r[2],
             "timestamp": r[3], "metadata": r[4]} for r in rows]


def list_analysis_ids(limit: int = 50) -> List[str]:
    """最近的分析 ID（用于 UI 历史回溯）。"""
    init()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT analysis_id FROM agent_traces"
            " GROUP BY analysis_id ORDER BY MAX(timestamp) DESC LIMIT ?", (limit,)).fetchall()
    return [r[0] for r in rows]
