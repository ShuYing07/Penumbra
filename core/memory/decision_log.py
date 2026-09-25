# -*- coding: utf-8 -*-
"""决策日志：每次分析完整落库（point-in-time 快照），三期将追加到期收益与反思。"""
from __future__ import annotations

import json

from core.config import now_cn
from core.data.cache import get_conn

_SCHEMA = """
CREATE TABLE IF NOT EXISTS decisions(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT, ticker TEXT, market TEXT, asof TEXT,
  price REAL, action TEXT, confidence INTEGER,
  position_pct INTEGER, stop_loss REAL, targets TEXT,
  horizon TEXT, entry TEXT, summary TEXT,
  scenarios TEXT, reasons TEXT, risks TEXT,
  signals TEXT, trader TEXT, risk_json TEXT,
  tokens TEXT, evaluated INTEGER DEFAULT 0,
  realized_return_pct REAL, reflection TEXT,
  ts_reflected TEXT
);
"""


def init() -> None:
    with get_conn() as conn:
        conn.executescript(_SCHEMA)
        # 旧库迁移：补 ts_reflected 列（2026-09-10 三期新增）
        cols = {r[1] for r in conn.execute("PRAGMA table_info(decisions)").fetchall()}
        if "ts_reflected" not in cols:
            conn.execute("ALTER TABLE decisions ADD COLUMN ts_reflected TEXT")


def save(ticker: str, market: str, asof: str, quote: dict, final: dict,
         signals: dict, trader: dict, risk: dict, tokens: dict) -> int:
    init()
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO decisions(
              ts,ticker,market,asof,price,action,confidence,position_pct,stop_loss,
              targets,horizon,entry,summary,scenarios,reasons,risks,
              signals,trader,risk_json,tokens)
              VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                now_cn().isoformat(timespec="seconds"), ticker, market, asof,
                final.get("price") or quote.get("price"),
                final.get("action"), final.get("confidence"),
                final.get("position_pct"), final.get("stop_loss"),
                json.dumps(final.get("targets", []), ensure_ascii=False),
                final.get("horizon", ""), final.get("entry", ""),
                final.get("summary", ""),
                json.dumps(final.get("scenarios", []), ensure_ascii=False),
                json.dumps(final.get("reasons", []), ensure_ascii=False),
                json.dumps(final.get("risks", []), ensure_ascii=False),
                json.dumps(signals, ensure_ascii=False),
                json.dumps(trader, ensure_ascii=False),
                json.dumps(risk, ensure_ascii=False),
                json.dumps(tokens, ensure_ascii=False),
            ),
        )
        return int(cur.lastrowid)


def list_recent(ticker: str | None = None, limit: int = 10) -> list[dict]:
    init()
    sql = "SELECT id,ts,ticker,asof,price,action,position_pct,confidence,evaluated,realized_return_pct FROM decisions"
    params: tuple = ()
    if ticker:
        sql += " WHERE ticker=?"
        params = (ticker,)
    sql += " ORDER BY id DESC LIMIT ?"
    params += (limit,)
    with get_conn() as conn:
        cols = ["id", "ts", "ticker", "asof", "price", "action",
                "position_pct", "confidence", "evaluated", "realized_return_pct"]
        return [dict(zip(cols, r)) for r in conn.execute(sql, params).fetchall()]
