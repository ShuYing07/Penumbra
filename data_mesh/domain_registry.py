# -*- coding: utf-8 -*-
"""Data Mesh：数据域注册表（领域驱动的数据去中心化）。

预置四大域：market_data（行情）/ news（新闻）/ fundamentals（基本面）/ user_data（用户）。
每个域：data_product、owner、schema、sla（可查、可审计）。
"""
from __future__ import annotations

from core.config import DATA_DIR

_DB = DATA_DIR / "data_mesh.db"
_SCHEMA = """
CREATE TABLE IF NOT EXISTS domains (
    domain_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    owner TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    schema_json TEXT NOT NULL DEFAULT '{}',
    sla_seconds INTEGER NOT NULL DEFAULT 300,
    updated_at REAL NOT NULL
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

# 预置域（种子）
SEED = [
    {"domain_id": "market_data", "name": "行情域", "owner": "data-team",
     "description": "K线/指数/资金流等行情数据",
     "schema": {"ticker": "str", "date": "date", "open": "float",
                "high": "float", "low": "float", "close": "float", "volume": "int"},
     "sla_seconds": 60},
    {"domain_id": "news", "name": "新闻域", "owner": "news-team",
     "description": "财经新闻/公告/研报聚合",
     "schema": {"source": "str", "title": "str", "ts": "datetime", "text": "str"},
     "sla_seconds": 300},
    {"domain_id": "fundamentals", "name": "基本面域", "owner": "fund-team",
     "description": "财务指标/估值/股东数据",
     "schema": {"ticker": "str", "report_date": "date", "metric": "str", "value": "float"},
     "sla_seconds": 600},
    {"domain_id": "user_data", "name": "用户域", "owner": "user-team",
     "description": "自选股/分析历史/决策记录（GDPR 可导出删除）",
     "schema": {"user_id": "str", "action": "str", "ts": "datetime"},
     "sla_seconds": 120},
]


def register_domain(domain_id: str, name: str, owner: str, description: str,
                    schema: dict, sla_seconds: int) -> None:
    import json
    import time
    with _conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO domains(domain_id,name,owner,description,schema_json,sla_seconds,updated_at)"
            " VALUES(?,?,?,?,?,?,?)",
            (domain_id, name, owner, description, json.dumps(schema, ensure_ascii=False),
             sla_seconds, time.time()))


def seed() -> int:
    for d in SEED:
        register_domain(**d)
    return len(SEED)


def list_domains() -> list[dict]:
    with _conn() as c:
        rows = c.execute("SELECT * FROM domains").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        import json
        d["schema"] = json.loads(d["schema_json"])
        out.append(d)
    return out


def get_domain(domain_id: str) -> dict | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM domains WHERE domain_id=?", (domain_id,)).fetchone()
    if row is None:
        return None
    d = dict(row)
    import json
    d["schema"] = json.loads(d["schema_json"])
    return d
