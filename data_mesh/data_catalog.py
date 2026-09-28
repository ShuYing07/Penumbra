# -*- coding: utf-8 -*-
"""Data Mesh：数据目录（按域检索数据产品 + 质量指标）。"""
from __future__ import annotations

import json
import time

from core.config import DATA_DIR

_DB = DATA_DIR / "data_mesh.db"
_SCHEMA = """
CREATE TABLE IF NOT EXISTS data_products (
    product_id TEXT PRIMARY KEY,
    domain_id TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    schema_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL DEFAULT '',
    quality_json TEXT NOT NULL DEFAULT '{}'   -- {rows, freshness_sec, completeness}
);
CREATE INDEX IF NOT EXISTS ix_products_domain ON data_products(domain_id);
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

def register_product(product_id: str, domain_id: str, name: str,
                     description: str, schema: dict,
                     updated_at: str = "", quality: dict | None = None) -> None:
    with _conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO data_products(product_id,domain_id,name,description,"
            " schema_json,updated_at,quality_json) VALUES(?,?,?,?,?,?,?)",
            (product_id, domain_id, name, description,
             json.dumps(schema, ensure_ascii=False), updated_at,
             json.dumps(quality or {}, ensure_ascii=False)))


def update_quality(product_id: str, quality: dict) -> None:
    with _conn() as c:
        c.execute("UPDATE data_products SET quality_json=? WHERE product_id=?",
                  (json.dumps(quality, ensure_ascii=False), product_id))


def search(domain_id: str | None = None, keyword: str = "") -> list[dict]:
    sql = "SELECT * FROM data_products"
    where, args = [], []
    if domain_id:
        where.append("domain_id=?")
        args.append(domain_id)
    if keyword:
        where.append("(name LIKE ? OR description LIKE ?)")
        args += [f"%{keyword}%", f"%{keyword}%"]
    if where:
        sql += " WHERE " + " AND ".join(where)
    with _conn() as c:
        rows = c.execute(sql, args).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["schema"] = json.loads(d["schema_json"])
        d["quality"] = json.loads(d["quality_json"])
        out.append(d)
    return out


def catalog_stats() -> dict:
    with _conn() as c:
        total = c.execute("SELECT COUNT(*) FROM data_products").fetchone()[0]
        by_domain = {r["domain_id"]: r["cnt"] for r in c.execute(
            "SELECT domain_id, COUNT(*) cnt FROM data_products GROUP BY domain_id").fetchall()}
    return {"total": total, "by_domain": by_domain}
