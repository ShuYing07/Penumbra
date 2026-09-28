# -*- coding: utf-8 -*-
"""协作工作流（企业版模块四）：共享研究空间 / 评论 / 版本控制。

数据表（独立 collab.db，避免与既有库耦合）：
- workspaces : 共享研究空间（名称、描述、创建者、状态）
- workspace_members : 空间成员（user_id -> workspace）
- comments    : 分析报告评论（关联 workspace + resource）
- versions    : 策略/报告版本（内容快照 + 版本号 + 提交说明）

功能：
- create_workspace / join_workspace / list_workspaces / archive_workspace
- add_comment / list_comments
- commit_version / list_versions / rollback_to（回滚=生成新版本快照，不物理删除）
"""
from __future__ import annotations

import logging
import sqlite3
import time
from pathlib import Path

log = logging.getLogger("stockai.collab")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS workspaces(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT DEFAULT '',
    owner_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',   -- active / archived
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS workspace_members(
    workspace_id INTEGER NOT NULL,
    user_id TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'member',     -- owner / member / viewer
    joined_at TEXT NOT NULL,
    PRIMARY KEY(workspace_id, user_id)
);
CREATE TABLE IF NOT EXISTS comments(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id INTEGER NOT NULL,
    resource TEXT NOT NULL,                  -- 如 SH600519 报告 / backtest:ma_cross
    user_id TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS versions(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id INTEGER NOT NULL,
    resource TEXT NOT NULL,                  -- 如 strategy:ma_cross
    version_no INTEGER NOT NULL,
    content TEXT NOT NULL,
    note TEXT DEFAULT '',
    user_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(workspace_id, resource, version_no)
)
"""


def _db() -> Path:
    root = Path(__file__).resolve().parents[1]
    p = root / "data" / "collab.db"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _conn():
    conn = sqlite3.connect(_db())
    conn.executescript(_SCHEMA)
    return conn


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ---------------------------------------------------------------- 空间

def create_workspace(name: str, owner_id: str, description: str = "") -> dict:
    with _conn() as conn:
        try:
            cur = conn.execute(
                "INSERT INTO workspaces(name, description, owner_id, status, created_at)"
                " VALUES(?,?,?,?,?)",
                (name, description, owner_id, "active", _now()))
            wid = cur.lastrowid
        except sqlite3.IntegrityError:
            raise ValueError(f"空间已存在: {name}")
        conn.execute(
            "INSERT INTO workspace_members(workspace_id, user_id, role, joined_at)"
            " VALUES(?,?,?,?)", (wid, owner_id, "owner", _now()))
    return {"id": wid, "name": name, "owner_id": owner_id, "status": "active"}


def join_workspace(workspace_id: int, user_id: str, role: str = "member") -> bool:
    with _conn() as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO workspace_members(workspace_id, user_id, role, joined_at)"
            " VALUES(?,?,?,?)", (workspace_id, user_id, role, _now()))
        return cur.rowcount > 0


def list_workspaces(user_id: str | None = None,
                    include_archived: bool = False) -> list[dict]:
    with _conn() as conn:
        sql = ("SELECT w.id,w.name,w.description,w.owner_id,w.status,w.created_at"
               " FROM workspaces w")
        args: list = []
        if user_id:
            sql += " JOIN workspace_members m ON m.workspace_id=w.id WHERE m.user_id=?"
            args.append(user_id)
            if not include_archived:
                sql += " AND w.status='active'"
        rows = conn.execute(sql + " ORDER BY w.id DESC", args).fetchall()
    k = ["id", "name", "description", "owner_id", "status", "created_at"]
    return [dict(zip(k, r)) for r in rows]


def archive_workspace(workspace_id: int, actor: str) -> bool:
    with _conn() as conn:
        cur = conn.execute(
            "UPDATE workspaces SET status='archived' WHERE id=? AND owner_id=?",
            (workspace_id, actor))
        return cur.rowcount > 0


# ---------------------------------------------------------------- 评论

def add_comment(workspace_id: int, resource: str, user_id: str, content: str) -> int:
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO comments(workspace_id, resource, user_id, content, created_at)"
            " VALUES(?,?,?,?,?)", (workspace_id, resource, user_id, content, _now()))
        return cur.lastrowid


def list_comments(workspace_id: int, resource: str | None = None,
                  limit: int = 100) -> list[dict]:
    with _conn() as conn:
        sql = "SELECT * FROM comments WHERE workspace_id=?"
        args: list = [workspace_id]
        if resource:
            sql += " AND resource=?"
            args.append(resource)
        sql += " ORDER BY id ASC LIMIT ?"
        args.append(limit)
        rows = conn.execute(sql, args).fetchall()
    k = ["id", "workspace_id", "resource", "user_id", "content", "created_at"]
    return [dict(zip(k, r)) for r in rows]


# ---------------------------------------------------------------- 版本控制

def commit_version(workspace_id: int, resource: str, content: str,
                   user_id: str, note: str = "") -> dict:
    """提交新版本（自动递增 version_no）。"""
    with _conn() as conn:
        row = conn.execute(
            "SELECT MAX(version_no) FROM versions WHERE workspace_id=? AND resource=?",
            (workspace_id, resource)).fetchone()
        vno = (row[0] or 0) + 1
        conn.execute(
            "INSERT INTO versions(workspace_id, resource, version_no, content, note,"
            " user_id, created_at) VALUES(?,?,?,?,?,?,?)",
            (workspace_id, resource, vno, content, note, user_id, _now()))
    return {"workspace_id": workspace_id, "resource": resource,
            "version_no": vno, "note": note}


def list_versions(workspace_id: int, resource: str) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT id, version_no, note, user_id, created_at FROM versions"
            " WHERE workspace_id=? AND resource=? ORDER BY version_no DESC",
            (workspace_id, resource)).fetchall()
    k = ["id", "version_no", "note", "user_id", "created_at"]
    return [dict(zip(k, r)) for r in rows]


def get_version(workspace_id: int, resource: str, version_no: int) -> dict | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT version_no, content, note, user_id, created_at FROM versions"
            " WHERE workspace_id=? AND resource=? AND version_no=?",
            (workspace_id, resource, version_no)).fetchone()
    if not row:
        return None
    k = ["version_no", "content", "note", "user_id", "created_at"]
    return dict(zip(k, row))


def rollback_to(workspace_id: int, resource: str, version_no: int,
                user_id: str) -> dict:
    """回滚到指定版本 = 把该版本内容作为新版本提交（不破坏历史）。"""
    v = get_version(workspace_id, resource, version_no)
    if v is None:
        raise ValueError(f"版本不存在: {resource} v{version_no}")
    return commit_version(workspace_id, resource, v["content"], user_id,
                          note=f"回滚自 v{version_no}")
