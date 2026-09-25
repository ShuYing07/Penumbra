# -*- coding: utf-8 -*-
"""SQLite 本地缓存（point-in-time 纪律：只 INSERT OR IGNORE，永不覆盖历史）。

表：
- daily_bars(ticker, date, OHLCV+amount, source, fetched_at)
- news(url, ticker, title, content, source, published_at, fetched_at)
- token_ledger(ts, node, model, prompt_tokens, completion_tokens, total, cost_cny)
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Iterable

import pandas as pd

from core.config import DB_PATH, now_cn

_SCHEMA = """
CREATE TABLE IF NOT EXISTS daily_bars(
  ticker TEXT NOT NULL,
  date TEXT NOT NULL,
  open REAL, high REAL, low REAL, close REAL, volume REAL, amount REAL,
  source TEXT, fetched_at TEXT,
  PRIMARY KEY(ticker, date)
);
CREATE TABLE IF NOT EXISTS news(
  url TEXT NOT NULL PRIMARY KEY,
  ticker TEXT, title TEXT, content TEXT, source TEXT,
  published_at TEXT, fetched_at TEXT
);
CREATE TABLE IF NOT EXISTS token_ledger(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT, node TEXT, model TEXT,
  prompt_tokens INTEGER, completion_tokens INTEGER, total INTEGER, cost_cny REAL
);
"""


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        conn.executescript(_SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(_SCHEMA)


def clear_all() -> None:
    """清空行情与新闻缓存（开发者调试用）；保留 token_ledger 与 decisions。"""
    with get_conn() as conn:
        conn.execute("DELETE FROM daily_bars")
        conn.execute("DELETE FROM news")


def upsert_bars(ticker: str, df: pd.DataFrame, source: str) -> int:
    """写入行情（已存在的日期不覆盖），返回新增行数。"""
    if df is None or len(df) == 0:
        return 0
    fetched = now_cn().isoformat(timespec="seconds")
    rows = [
        (
            ticker,
            pd.Timestamp(idx).strftime("%Y-%m-%d"),
            _num(row.get("open")), _num(row.get("high")), _num(row.get("low")),
            _num(row.get("close")), _num(row.get("volume")), _num(row.get("amount")),
            source, fetched,
        )
        for idx, row in zip(df.index, df.to_dict("records"))
    ]
    with get_conn() as conn:
        before = conn.total_changes
        conn.executemany(
            "INSERT OR IGNORE INTO daily_bars"
            "(ticker,date,open,high,low,close,volume,amount,source,fetched_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
        return max(0, conn.total_changes - before)


def load_bars(ticker: str) -> pd.DataFrame:
    with get_conn() as conn:
        df = pd.read_sql_query(
            "SELECT date,open,high,low,close,volume,amount FROM daily_bars "
            "WHERE ticker=? ORDER BY date",
            conn, params=(ticker,),
        )
    if len(df) == 0:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume", "amount"])
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date")


def bars_coverage(ticker: str) -> tuple[str | None, str | None, int]:
    with get_conn() as conn:
        cur = conn.execute(
            "SELECT MIN(date),MAX(date),COUNT(*) FROM daily_bars WHERE ticker=?", (ticker,))
        mn, mx, cnt = cur.fetchone()
    return mn, mx, cnt


def upsert_news(items: Iterable[dict]) -> int:
    fetched = now_cn().isoformat(timespec="seconds")
    rows = [
        (it["url"], it.get("ticker"), it.get("title"), it.get("content"),
         it.get("source"), it.get("published_at"), fetched)
        for it in items
    ]
    if not rows:
        return 0
    with get_conn() as conn:
        before = conn.total_changes
        conn.executemany(
            "INSERT OR IGNORE INTO news(url,ticker,title,content,source,published_at,fetched_at)"
            " VALUES (?,?,?,?,?,?,?)",
            rows,
        )
        return max(0, conn.total_changes - before)


def load_news(ticker: str | None = None, limit: int = 15) -> list[dict]:
    sql = "SELECT title,content,source,url,published_at FROM news"
    params: tuple = ()
    if ticker:
        sql += " WHERE ticker=?"
        params = (ticker,)
    sql += " ORDER BY published_at DESC LIMIT ?"
    params = params + (limit,)
    with get_conn() as conn:
        cols = ["title", "content", "source", "url", "published_at"]
        return [dict(zip(cols, r)) for r in conn.execute(sql, params).fetchall()]


def record_tokens(node: str, model: str, prompt: int, completion: int, cost: float) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO token_ledger(ts,node,model,prompt_tokens,completion_tokens,total,cost_cny)"
            " VALUES (?,?,?,?,?,?,?)",
            (now_cn().isoformat(timespec="seconds"), node, model, prompt, completion,
             prompt + completion, cost),
        )


def token_cost_total() -> tuple[int, float]:
    with get_conn() as conn:
        row = conn.execute("SELECT COALESCE(SUM(total),0),COALESCE(SUM(cost_cny),0) FROM token_ledger").fetchone()
    return int(row[0]), round(float(row[1]), 4)


def _num(x):
    try:
        if x is None or pd.isna(x):
            return None
        return float(x)
    except (TypeError, ValueError):
        return None
