# -*- coding: utf-8 -*-
"""长期记忆：分析历史持久化 + 知识沉淀。"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from core.config import now_cn
from core.data.cache import get_conn

_DB = Path.home() / ".shuying" / "memory.db"
_DB.parent.mkdir(parents=True, exist_ok=True)


def _conn():
    c = sqlite3.connect(str(_DB), timeout=30)
    c.row_factory = sqlite3.Row
    return c


_SCHEMA = """
CREATE TABLE IF NOT EXISTS analysis_history(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT, ticker TEXT, name TEXT,
  price REAL, chg_pct REAL,
  rsi REAL, macd_signal TEXT,
  summary TEXT, source TEXT
);
CREATE TABLE IF NOT EXISTS knowledge_facts(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT, ticker TEXT, fact TEXT,
  source TEXT
);
CREATE TABLE IF NOT EXISTS user_prefs(
  key TEXT PRIMARY KEY,
  value TEXT
);
"""


def init() -> None:
    with _conn() as c:
        c.executescript(_SCHEMA)


def save_analysis(ticker: str, name: str, price: float, chg_pct: float,
                  rsi: float, macd_signal: str, summary: str, source: str) -> int:
    """每次分析完成后调用，沉淀到长期记忆。"""
    init()
    with _conn() as c:
        cur = c.execute(
            """INSERT INTO analysis_history
            (ts,ticker,name,price,chg_pct,rsi,macd_signal,summary,source)
            VALUES (?,?,?,?,?,?,?,?,?)""",
            (now_cn().isoformat(timespec="seconds"), ticker, name,
             price, chg_pct, rsi, macd_signal, summary[:500], source),
        )
        return cur.lastrowid


def list_history(ticker: str | None = None, limit: int = 50) -> list[dict]:
    init()
    sql = "SELECT * FROM analysis_history"
    params: tuple = ()
    if ticker:
        sql += " WHERE ticker=?"
        params = (ticker,)
    sql += " ORDER BY id DESC LIMIT ?"
    params += (limit,)
    with _conn() as c:
        return [dict(r) for r in c.execute(sql, params).fetchall()]


def add_fact(ticker: str, fact: str, source: str = "ai") -> None:
    """沉淀一条知识（如"AAPL RSI=61.2，MACD无交叉"）。"""
    init()
    with _conn() as c:
        c.execute(
            "INSERT INTO knowledge_facts(ts,ticker,fact,source) VALUES (?,?,?,?)",
            (now_cn().isoformat(timespec="seconds"), ticker, fact, source),
        )


def get_pref(key: str, default: str = "") -> str:
    init()
    with _conn() as c:
        r = c.execute("SELECT value FROM user_prefs WHERE key=?", (key,)).fetchone()
        return r["value"] if r else default


def set_pref(key: str, value: str) -> None:
    init()
    with _conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO user_prefs(key,value) VALUES (?,?)",
            (key, value),
        )


def export_json(ticker: str | None = None) -> str:
    """导出历史分析为JSON。"""
    data = {
        "history": list_history(ticker, limit=1000),
        "exported_at": now_cn().isoformat(),
    }
    return json.dumps(data, ensure_ascii=False, indent=2)
