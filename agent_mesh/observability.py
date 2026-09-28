# -*- coding: utf-8 -*-
"""Agent Mesh：可观测性（通信日志 + 可解释性账本）。

- mesh_comm_log：Agent 间通信记录（时间/源/目标/操作/耗时/结果）；
- mesh_ledger：决策账本（decision_id + 完整推理链路 JSON + 摘要），
  追加式写入，配合 security.audit_ledger 的哈希链实现防篡改。
"""
from __future__ import annotations

import json
import time

from core.config import DATA_DIR

_DB = DATA_DIR / "agent_mesh.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS mesh_comm_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    source TEXT NOT NULL,
    target TEXT NOT NULL,
    action TEXT NOT NULL,
    elapsed_ms REAL NOT NULL DEFAULT 0,
    ok INTEGER NOT NULL DEFAULT 1,
    detail TEXT
);
CREATE TABLE IF NOT EXISTS mesh_ledger (
    decision_id TEXT PRIMARY KEY,
    ts REAL NOT NULL,
    agent_id TEXT NOT NULL,
    summary TEXT NOT NULL,
    chain TEXT NOT NULL          -- JSON: 完整推理链路
);
CREATE INDEX IF NOT EXISTS ix_comm_ts ON mesh_comm_log(ts);
"""


def _conn():
    import sqlite3
    from contextlib import closing, contextmanager

    @contextmanager
    def _open():
        con = sqlite3.connect(_DB)
        con.row_factory = sqlite3.Row
        con.executescript(_SCHEMA)
        with closing(con):
            yield con
            con.commit()

    return _open()

def log_comm(source: str, target: str, action: str,
             elapsed_ms: float = 0.0, ok: bool = True, detail: str = "") -> None:
    with _conn() as c:
        c.execute(
            "INSERT INTO mesh_comm_log(ts,source,target,action,elapsed_ms,ok,detail)"
            " VALUES(?,?,?,?,?,?,?)",
            (time.time(), source, target, action, elapsed_ms, int(ok), detail))


def record_decision(decision_id: str, agent_id: str, summary: str,
                    chain: list[dict]) -> None:
    """写入可解释性账本（追加式；幂等按 decision_id）。"""
    with _conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO mesh_ledger(decision_id,ts,agent_id,summary,chain)"
            " VALUES(?,?,?,?,?)",
            (decision_id, time.time(), agent_id, summary,
             json.dumps(chain, ensure_ascii=False)))


def get_decision(decision_id: str) -> dict | None:
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM mesh_ledger WHERE decision_id=?", (decision_id,)).fetchone()
    if row is None:
        return None
    d = dict(row)
    d["chain"] = json.loads(d["chain"])
    return d


def recent_comm(limit: int = 50) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM mesh_comm_log ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def recent_decisions(limit: int = 20) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT decision_id,ts,agent_id,summary FROM mesh_ledger"
            " ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]
