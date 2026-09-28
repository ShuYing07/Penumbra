# -*- coding: utf-8 -*-
"""关键操作审计日志（企业版模块一）。

与 core/audit_trail.py（AI 分析推理审计）互补：本模块记录**用户级关键操作**
（登录、分析、导出、删除、权限变更、数据源变更），满足 SOC 2 / 监管审计要求。

- 不可篡改：追加式写入（仅 INSERT，无 UPDATE/DELETE 接口），每条带 UTC 时间戳；
- 可导出 CSV：满足审计取证与合规导出；
- 落库位置：data/audit.db 的 op_audit 表（与现有 ai 审计表并存）。
"""
from __future__ import annotations

import csv
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("stockai.audit")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS op_audit(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    user_id TEXT NOT NULL,
    action TEXT NOT NULL,
    resource TEXT,
    detail TEXT,
    ip TEXT
)"""


def _db_path() -> Path:
    root = Path(__file__).resolve().parents[1]
    p = root / "data" / "audit.db"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _conn():
    conn = sqlite3.connect(_db_path())
    conn.execute(_SCHEMA)
    return conn


def log_operation(user_id: str, action: str, detail: str = "",
                  resource: str = "", ip: str = "") -> int:
    """追加一条操作审计（幂等建表）。返回记录 id。"""
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO op_audit(ts, user_id, action, resource, detail, ip)"
            " VALUES(?,?,?,?,?,?)",
            (datetime.now(timezone.utc).isoformat(), user_id, action,
             resource, detail, ip),
        )
        return cur.lastrowid


def query_audit(user_id: str | None = None, action: str | None = None,
                limit: int = 200) -> list[dict]:
    with _conn() as conn:
        sql = "SELECT * FROM op_audit WHERE 1=1"
        args: list = []
        if user_id:
            sql += " AND user_id=?"
            args.append(user_id)
        if action:
            sql += " AND action=?"
            args.append(action)
        sql += " ORDER BY id DESC LIMIT ?"
        args.append(limit)
        rows = conn.execute(sql, args).fetchall()
    cols = ["id", "ts", "user_id", "action", "resource", "detail", "ip"]
    return [dict(zip(cols, r)) for r in rows]


def export_csv(out_path: str | None = None) -> str:
    """导出全部审计日志为 CSV（合规取证）。"""
    rows = query_audit(limit=100000)
    out = out_path or str(Path(_db_path()).parent / "audit_export.csv")
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["id", "ts", "user_id", "action", "resource", "detail", "ip"])
        for r in rows:
            w.writerow([r[k] for k in ["id", "ts", "user_id", "action",
                                       "resource", "detail", "ip"]])
    return out


def count_audit() -> int:
    with _conn() as conn:
        return conn.execute("SELECT COUNT(*) FROM op_audit").fetchone()[0]
