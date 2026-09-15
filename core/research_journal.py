# -*- coding: utf-8 -*-
"""研究记录与复盘日志。

为每次分析提供个人笔记，支持按股票/时间检索，并生成复盘报告：
期间分析记录、置信度分布、用户笔记摘要。
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from core.config import DATA_DIR, now_cn

_DB = Path(DATA_DIR) / "research_journal.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS research_journal(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT,
  stock_code TEXT,
  note TEXT,
  tags TEXT
);
"""


def _conn():
    _DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB))
    conn.row_factory = sqlite3.Row
    return conn


def init() -> None:
    with _conn() as conn:
        conn.executescript(_SCHEMA)


def save_research_note(stock_code: str, note: str, tags: list[str] | str | None = None) -> int | None:
    try:
        init()
        tags_text = ", ".join(tags) if isinstance(tags, (list, tuple)) else str(tags or "")
        with _conn() as conn:
            cur = conn.execute(
                "INSERT INTO research_journal(ts, stock_code, note, tags) VALUES (?,?,?,?)",
                (now_cn().isoformat(timespec="seconds"), stock_code, note or "", tags_text),
            )
            return int(cur.lastrowid)
    except Exception:  # noqa: BLE001
        return None


def get_research_history(stock_code: str, days: int = 30) -> list[dict]:
    init()
    since = (now_cn() - timedelta(days=days)).isoformat(timespec="seconds")
    with _conn() as conn:
        rows = conn.execute(
            "SELECT id, ts, stock_code, note, tags FROM research_journal "
            "WHERE stock_code=? AND ts>=? ORDER BY id DESC",
            (stock_code, since)).fetchall()
        cols = ["id", "ts", "stock_code", "note", "tags"]
        return [dict(zip(cols, r)) for r in rows]


def generate_review_report(stock_code: str, days: int = 30) -> dict:
    """生成复盘报告：笔记列表 + 期间分析置信度分布（来自 decision_logger）。"""
    notes = get_research_history(stock_code, days)
    confs: list[float] = []
    try:
        from decision_logger import get_decision_history
        for rec in get_decision_history(stock_code, limit=200):
            c = rec.get("confidence_score")
            if isinstance(c, (int, float)):
                confs.append(float(c))
    except Exception:  # noqa: BLE001
        pass

    if confs:
        dist = {
            "高(>=70)": sum(1 for c in confs if c >= 70),
            "中(40-70)": sum(1 for c in confs if 40 <= c < 70),
            "低(<40)": sum(1 for c in confs if c < 40),
            "平均置信度": round(sum(confs) / len(confs), 1),
        }
    else:
        dist = {}

    return {
        "stock_code": stock_code,
        "days": days,
        "note_count": len(notes),
        "notes": notes,
        "confidence_distribution": dist,
        "analysis_count": len(confs),
        "generated_at": now_cn().isoformat(timespec="seconds"),
    }
