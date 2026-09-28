# -*- coding: utf-8 -*-
"""Agent Mesh：Agent 注册中心（注册/发现/注销）。

SQLite 持久化（data/agent_mesh.db）；标准库实现，无第三方依赖。
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from core.config import DATA_DIR

_DB = DATA_DIR / "agent_mesh.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS agents (
    agent_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    version TEXT NOT NULL,
    capabilities TEXT NOT NULL,      -- JSON list
    endpoint TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    registered_at REAL NOT NULL
);
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

def register_agent(name: str, version: str, capabilities: list[str],
                   endpoint: str = "") -> dict:
    """注册 Agent；同名同版本视为更新（幂等）。"""
    agent_id = uuid.uuid4().hex[:12]
    with _conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO agents(agent_id,name,version,capabilities,endpoint,status,registered_at)"
            " VALUES(?,?,?,?,?,'active',?)",
            (agent_id, name, version, json.dumps(capabilities, ensure_ascii=False),
             endpoint, time.time()))
    return get_agent(agent_id)


def get_agent(agent_id: str) -> dict | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM agents WHERE agent_id=?", (agent_id,)).fetchone()
    if row is None:
        return None
    d = dict(row)
    d["capabilities"] = json.loads(d["capabilities"])
    return d


def discover(capability: str | None = None, active_only: bool = True) -> list[dict]:
    """按能力发现 Agent；capability=None 时返回全部。"""
    sql = "SELECT * FROM agents"
    where, args = [], []
    if active_only:
        where.append("status='active'")
    if capability:
        where.append("capabilities LIKE ?")
        args.append(f"%{capability}%")
    if where:
        sql += " WHERE " + " AND ".join(where)
    with _conn() as c:
        rows = c.execute(sql, args).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["capabilities"] = json.loads(d["capabilities"])
        out.append(d)
    return out


def unregister(agent_id: str) -> bool:
    with _conn() as c:
        cur = c.execute("DELETE FROM agents WHERE agent_id=?", (agent_id,))
    return cur.rowcount > 0


def set_status(agent_id: str, status: str) -> None:
    with _conn() as c:
        c.execute("UPDATE agents SET status=? WHERE agent_id=?", (status, agent_id))


def count() -> int:
    with _conn() as c:
        return c.execute("SELECT COUNT(*) FROM agents").fetchone()[0]
