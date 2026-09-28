# -*- coding: utf-8 -*-
"""Agent Mesh：策略引擎（PEP 策略执行点 / PDP 策略决策点）。

策略表：subject_agent -> (action, resource) -> allowed。
PEP 在调用点拦截，PDP 查询策略并裁决；默认拒绝（deny-by-default）。
"""
from __future__ import annotations

import json
import time

from core.config import DATA_DIR

_DB = DATA_DIR / "agent_mesh.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS mesh_policies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject TEXT NOT NULL,
    action TEXT NOT NULL,
    resource TEXT NOT NULL,
    allowed INTEGER NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_policy ON mesh_policies(subject, action, resource);
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

def set_policy(subject: str, action: str, resource: str, allowed: bool) -> None:
    with _conn() as c:
        c.execute(
            "INSERT INTO mesh_policies(subject,action,resource,allowed,updated_at)"
            " VALUES(?,?,?,?,?) "
            "ON CONFLICT(subject,action,resource) DO UPDATE SET allowed=?,updated_at=?",
            (subject, action, resource, int(allowed), time.time(), int(allowed), time.time()))


def allow(subject: str, action: str, resource: str) -> None:
    set_policy(subject, action, resource, True)


def deny(subject: str, action: str, resource: str) -> None:
    set_policy(subject, action, resource, False)


def check(subject: str, action: str, resource: str) -> bool:
    """PDP 裁决：无显式策略 = 拒绝。"""
    with _conn() as c:
        row = c.execute(
            "SELECT allowed FROM mesh_policies WHERE subject=? AND action=? AND resource=?",
            (subject, action, resource)).fetchone()
    return bool(row and row["allowed"])


def enforce(subject: str, action: str, resource: str) -> None:
    """PEP 执行：拒绝时抛 PermissionError。"""
    if not check(subject, action, resource):
        raise PermissionError(f"策略拒绝：{subject} 无权执行 {action}@{resource}")


def policies() -> list[dict]:
    with _conn() as c:
        rows = c.execute("SELECT subject,action,resource,allowed FROM mesh_policies").fetchall()
    return [dict(r) for r in rows]
