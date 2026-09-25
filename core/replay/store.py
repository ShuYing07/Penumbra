# -*- coding: utf-8 -*-
"""AI 回放信号持久化（独立表，不污染真实 decisions/反思/模拟盘/RAG）。"""
from __future__ import annotations

import json

from core.config import now_cn
from core.data.cache import get_conn

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_replay_signals(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  schema_version INTEGER NOT NULL DEFAULT 1,
  batch_id TEXT NOT NULL,
  ticker TEXT NOT NULL,
  market TEXT NOT NULL,
  engine TEXT NOT NULL,
  asof TEXT NOT NULL,
  price REAL,
  action TEXT,
  confidence INTEGER,
  position_pct INTEGER,
  final_json TEXT,
  ret_5 REAL, ret_10 REAL, ret_20 REAL,
  hit_5 INTEGER, hit_10 INTEGER, hit_20 INTEGER,
  evaluated INTEGER NOT NULL DEFAULT 0,
  error TEXT,
  created_at TEXT NOT NULL,
  UNIQUE(batch_id, ticker, asof));
CREATE INDEX IF NOT EXISTS idx_replay_batch ON ai_replay_signals(batch_id);
"""

_COLS = ("id,schema_version,batch_id,ticker,market,engine,asof,price,action,"
         "confidence,position_pct,final_json,ret_5,ret_10,ret_20,"
         "hit_5,hit_10,hit_20,evaluated,error,created_at")


def init() -> None:
    with get_conn() as conn:
        conn.executescript(_SCHEMA)


def save_signal(batch_id: str, ticker: str, market: str, engine: str,
                asof: str, final: dict, error: str = "") -> int:
    """插入一条回放信号（评估字段留空）；同批次同标的同时点重复则替换。"""
    init()
    ts = now_cn().isoformat(timespec="seconds")
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT OR REPLACE INTO ai_replay_signals(
               schema_version,batch_id,ticker,market,engine,asof,price,action,
               confidence,position_pct,final_json,evaluated,error,created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,0,?,?)""",
            (SCHEMA_VERSION, batch_id, ticker.upper(), market, engine, asof,
             final.get("price"), final.get("action"),
             final.get("confidence"), final.get("position_pct"),
             json.dumps(final, ensure_ascii=False, default=str),
             error, ts),
        )
        return int(cur.lastrowid)


def list_batch(batch_id: str) -> list[dict]:
    init()
    with get_conn() as conn:
        rows = conn.execute(
            f"SELECT {_COLS} FROM ai_replay_signals WHERE batch_id=? ORDER BY asof",
            (batch_id,)).fetchall()
    return [dict(zip(_COLS.split(","), r)) for r in rows]


def batches(limit: int = 50) -> list[dict]:
    """历史批次概览（去重 batch_id + 聚合）。"""
    init()
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT batch_id, ticker, engine, COUNT(*),
                      MIN(asof), MAX(asof), SUM(evaluated), MAX(created_at)
               FROM ai_replay_signals GROUP BY batch_id
               ORDER BY MAX(created_at) DESC LIMIT ?""", (limit,)).fetchall()
    keys = ("batch_id", "ticker", "engine", "n", "start", "end",
            "evaluated", "created_at")
    return [dict(zip(keys, r)) for r in rows]


def update_evaluation(sig_id: int, ret: dict, hit: dict) -> None:
    """写回各持有期收益/方向命中并置 evaluated=1。"""
    with get_conn() as conn:
        conn.execute(
            """UPDATE ai_replay_signals SET
               ret_5=?,ret_10=?,ret_20=?,hit_5=?,hit_10=?,hit_20=?,evaluated=1
               WHERE id=?""",
            (ret.get(5), ret.get(10), ret.get(20),
             hit.get(5), hit.get(10), hit.get(20), sig_id))
