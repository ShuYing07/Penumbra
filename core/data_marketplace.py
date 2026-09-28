# -*- coding: utf-8 -*-
"""第三方数据源市场（企业版模块五）：数据源订阅管理。

- 内置数据源目录（Wind / Tushare / Polygon / Alpha Vantage / AkShare / 自定义）；
- subscribe / unsubscribe / list_subscriptions：订阅状态本地持久化；
- 定价占位：企业版与数据商结算由部署方配置，本模块仅管理订阅状态。
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

CATALOG = [
    {"id": "wind",       "name": "Wind 万得",     "type": "premium",
     "desc": "机构级行情/财务，需商业授权", "official": "https://www.wind.com.cn"},
    {"id": "tushare",    "name": "Tushare Pro",   "type": "freemium",
     "desc": "A股/指数/财务，积分制",       "official": "https://tushare.pro"},
    {"id": "polygon",    "name": "Polygon.io",    "type": "premium",
     "desc": "美股/加密全量数据",           "official": "https://polygon.io"},
    {"id": "alpha_vantage", "name": "Alpha Vantage", "type": "freemium",
     "desc": "全球行情 REST API",           "official": "https://www.alphavantage.co"},
    {"id": "akshare",    "name": "AkShare(内置)", "type": "free",
     "desc": "开源免费数据源，桌面版默认",   "official": "https://akshare.akfamily.xyz"},
]


def _db() -> Path:
    root = Path(__file__).resolve().parents[1]
    p = root / "data" / "data_market.db"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _init() -> None:
    with sqlite3.connect(_db()) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS subscriptions(
                tenant_id TEXT NOT NULL,
                source_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                subscribed_at TEXT NOT NULL,
                api_key_hint TEXT DEFAULT '',
                PRIMARY KEY(tenant_id, source_id)
            )""")


def list_catalog() -> list[dict]:
    return CATALOG


def subscribe(tenant_id: str, source_id: str, api_key_hint: str = "") -> bool:
    _init()
    if source_id not in {s["id"] for s in CATALOG}:
        raise ValueError(f"未知数据源: {source_id}")
    with sqlite3.connect(_db()) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO subscriptions(tenant_id, source_id, status,"
            " subscribed_at, api_key_hint) VALUES(?,?,?,?,?)",
            (tenant_id, source_id, "active",
             time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), api_key_hint))
    return True


def unsubscribe(tenant_id: str, source_id: str) -> bool:
    _init()
    with sqlite3.connect(_db()) as conn:
        cur = conn.execute(
            "UPDATE subscriptions SET status='disabled' WHERE tenant_id=? AND source_id=?",
            (tenant_id, source_id))
        return cur.rowcount > 0


def list_subscriptions(tenant_id: str) -> list[dict]:
    _init()
    with sqlite3.connect(_db()) as conn:
        rows = conn.execute(
            "SELECT source_id, status, subscribed_at, api_key_hint FROM subscriptions"
            " WHERE tenant_id=?", (tenant_id,)).fetchall()
    k = ["source_id", "status", "subscribed_at", "api_key_hint"]
    return [dict(zip(k, r)) for r in rows]


def active_sources(tenant_id: str) -> list[str]:
    return [s["source_id"] for s in list_subscriptions(tenant_id)
            if s["status"] == "active"]
