# -*- coding: utf-8 -*-
"""自选股 + 盯盘条件持久化（SQLite，沿用 cache.get_conn）。

表 watchlist：每只自选股一行，存盯盘条件原文。解析结果不落库——
每次扫描重解析，规则升级即生效、无脏数据。last_trigger_at 防同一条件
短时间内反复弹窗（间隔由 STOCKAI_RETRIGGER_MIN 控制，默认 60 分钟）。
"""
from __future__ import annotations

from core.config import now_cn
from core.data.cache import get_conn

_SCHEMA = """
CREATE TABLE IF NOT EXISTS watchlist(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ticker TEXT NOT NULL,
  market TEXT NOT NULL,
  condition TEXT,
  note TEXT,
  enabled INTEGER NOT NULL DEFAULT 1,
  added_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  last_trigger_at TEXT,
  UNIQUE(ticker));
CREATE INDEX IF NOT EXISTS idx_watchlist_enabled ON watchlist(enabled);
"""

_COLS = ("ticker,market,condition,note,enabled,added_at,updated_at,last_trigger_at")


def init() -> None:
    with get_conn() as conn:
        conn.executescript(_SCHEMA)


def _row(row) -> dict:
    return {
        "ticker": row[0], "market": row[1], "condition": row[2] or "",
        "note": row[3] or "", "enabled": bool(row[4]),
        "added_at": row[5], "updated_at": row[6], "last_trigger_at": row[7],
    }


def add(ticker: str, market: str, condition: str = "", note: str = "") -> bool:
    """新增自选股；已存在则返回 False。"""
    ts = now_cn().isoformat(timespec="seconds")
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO watchlist"
            "(ticker,market,condition,note,enabled,added_at,updated_at)"
            " VALUES(?,?,?,?,1,?,?)",
            (ticker.upper(), market, condition, note, ts, ts),
        )
        return cur.rowcount > 0


def list_all() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            f"SELECT {_COLS} FROM watchlist ORDER BY market,ticker"
        ).fetchall()
    return [_row(r) for r in rows]


def list_enabled() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            f"SELECT {_COLS} FROM watchlist WHERE enabled=1 ORDER BY market,ticker"
        ).fetchall()
    return [_row(r) for r in rows]


def get(ticker: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            f"SELECT {_COLS} FROM watchlist WHERE ticker=?", (ticker.upper(),)
        ).fetchone()
    return _row(row) if row else None


def update(ticker: str, condition: str | None = None, note: str | None = None) -> None:
    """更新条件/备注（传 None 表示不改该字段）。"""
    cur = get(ticker)
    if cur is None:
        return
    new_cond = condition if condition is not None else cur["condition"]
    new_note = note if note is not None else cur["note"]
    ts = now_cn().isoformat(timespec="seconds")
    with get_conn() as conn:
        conn.execute(
            "UPDATE watchlist SET condition=?,note=?,updated_at=? WHERE ticker=?",
            (new_cond, new_note, ts, ticker.upper()),
        )


def set_enabled(ticker: str, enabled: bool) -> None:
    ts = now_cn().isoformat(timespec="seconds")
    with get_conn() as conn:
        conn.execute(
            "UPDATE watchlist SET enabled=?,updated_at=? WHERE ticker=?",
            (1 if enabled else 0, ts, ticker.upper()),
        )


def remove(ticker: str) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM watchlist WHERE ticker=?", (ticker.upper(),))


def set_last_trigger(ticker: str, ts: str | None = None) -> None:
    ts = ts or now_cn().isoformat(timespec="seconds")
    with get_conn() as conn:
        conn.execute(
            "UPDATE watchlist SET last_trigger_at=? WHERE ticker=?",
            (ts, ticker.upper()),
        )
