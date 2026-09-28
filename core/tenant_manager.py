# -*- coding: utf-8 -*-
"""多租户架构基础（企业版模块二）。

设计：**独立 SQLite 文件 per-tenant**（轻量级多租户，适合桌面/私有化部署起点，
无需 PostgreSQL；升级路径见 docs/ENTERPRISE.md）。

- tenant_register() : 注册租户，创建独立数据库文件 data/tenants/{id}.db；
- tenant_activate() / tenant_disable() : 租户生命周期管理；
- tenant_conn(tenant_id) : 数据隔离中间件 —— 返回该租户专属连接，
  任何代码只经此入口访问租户数据，从源头保证隔离；
- 元数据（租户列表、状态）集中存 data/tenants.db，不含任何业务数据。
"""
from __future__ import annotations

import logging
import sqlite3
import time
import uuid
from pathlib import Path

log = logging.getLogger("stockai.tenant")

STATUS_ACTIVE = "active"
STATUS_DISABLED = "disabled"


def _meta_db() -> Path:
    root = Path(__file__).resolve().parents[1]
    p = root / "data" / "tenants.db"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _tenant_dir() -> Path:
    root = Path(__file__).resolve().parents[1]
    p = root / "data" / "tenants"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _init_meta() -> None:
    with sqlite3.connect(_meta_db()) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tenants(
                tenant_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                db_path TEXT NOT NULL,
                created_at TEXT NOT NULL,
                plan TEXT NOT NULL DEFAULT 'free'
            )""")


def tenant_register(name: str, plan: str = "free") -> dict:
    """注册新租户，创建独立数据库文件。返回租户信息。"""
    _init_meta()
    tenant_id = "t_" + uuid.uuid4().hex[:12]
    db_path = str(_tenant_dir() / f"{tenant_id}.db")
    # 创建租户专属库（建核心业务表骨架）
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS workspace(id INTEGER PRIMARY KEY,"
                     " name TEXT, created_at TEXT)")
        conn.execute("CREATE TABLE IF NOT EXISTS tenant_meta(key TEXT PRIMARY KEY, value TEXT)")
    with sqlite3.connect(_meta_db()) as conn:
        conn.execute(
            "INSERT INTO tenants(tenant_id, name, status, db_path, created_at, plan)"
            " VALUES(?,?,?,?,?,?)",
            (tenant_id, name, STATUS_ACTIVE, db_path,
             time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), plan),
        )
    return {"tenant_id": tenant_id, "name": name, "status": STATUS_ACTIVE,
            "db_path": db_path, "plan": plan}


def tenant_set_status(tenant_id: str, status: str) -> bool:
    """激活/禁用租户。"""
    _init_meta()
    if status not in (STATUS_ACTIVE, STATUS_DISABLED):
        raise ValueError(f"非法状态: {status}")
    with sqlite3.connect(_meta_db()) as conn:
        cur = conn.execute("UPDATE tenants SET status=? WHERE tenant_id=?",
                           (status, tenant_id))
        return cur.rowcount > 0


def tenant_info(tenant_id: str) -> dict | None:
    _init_meta()
    with sqlite3.connect(_meta_db()) as conn:
        row = conn.execute("SELECT tenant_id,name,status,db_path,created_at,plan"
                           " FROM tenants WHERE tenant_id=?", (tenant_id,)).fetchone()
    if not row:
        return None
    k = ["tenant_id", "name", "status", "db_path", "created_at", "plan"]
    return dict(zip(k, row))


def list_tenants(status: str | None = None) -> list[dict]:
    _init_meta()
    with sqlite3.connect(_meta_db()) as conn:
        if status:
            rows = conn.execute("SELECT tenant_id,name,status,db_path,created_at,plan"
                                " FROM tenants WHERE status=?", (status,)).fetchall()
        else:
            rows = conn.execute("SELECT tenant_id,name,status,db_path,created_at,plan"
                                " FROM tenants").fetchall()
    k = ["tenant_id", "name", "status", "db_path", "created_at", "plan"]
    return [dict(zip(k, r)) for r in rows]


def tenant_conn(tenant_id: str) -> sqlite3.Connection:
    """数据隔离中间件：返回租户专属连接（业务代码的唯一数据入口）。

    - 租户不存在或已禁用 → 拒绝访问；
    - 返回的连接带 context manager 语义（调用方 with 使用）。
    """
    info = tenant_info(tenant_id)
    if info is None:
        raise PermissionError(f"租户不存在: {tenant_id}")
    if info["status"] != STATUS_ACTIVE:
        raise PermissionError(f"租户已禁用: {tenant_id}")
    conn = sqlite3.connect(info["db_path"])
    conn.row_factory = sqlite3.Row
    return conn


def isolate(tables: list[str]) -> callable:
    """装饰器：把函数的数据访问自动切到指定租户库。

    用法：
        @isolate(["workspace"])
        def list_workspaces(tenant_id: str) -> list: ...
    函数签名需以 tenant_id 为第一个参数；装饰器打开租户连接，
    把以 conn 为名的关键字参数注入。
    """
    def deco(fn):
        def wrapper(tenant_id: str, *args, **kwargs):
            with tenant_conn(tenant_id) as conn:
                kwargs["conn"] = conn
                return fn(tenant_id, *args, **kwargs)
        return wrapper
    return deco
