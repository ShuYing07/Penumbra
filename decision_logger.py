# -*- coding: utf-8 -*-
"""持久化决策日志（AI 分析侧）。

与 core/memory/decision_log.py（交易决策快照）不同，本模块专门记录
"AI 分析报告"层的结果：每次技术面/基本面/舆情/多空辩论分析完成后，
把原始输出、结构化输出、置信度、数据来源整体落库，供历史回溯与复盘。

设计要点：
- 独立 SQLite 文件（data/ai_analysis_log.db），point-in-time 只增不改；
- structured_output 以 JSON 文本存储，Pydantic 解析失败时降级存原始文本并标记；
- 全部异常静默兜底：日志模块任何失败都不得影响主分析流程。
"""
from __future__ import annotations

import csv
import io
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from core.config import DATA_DIR, now_cn

_DB_PATH = Path(DATA_DIR) / "ai_analysis_log.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS decision_log(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  timestamp TEXT NOT NULL,
  stock_code TEXT NOT NULL,
  stock_name TEXT DEFAULT '',
  model_used TEXT DEFAULT '',
  analysis_type TEXT DEFAULT '技术面',
  raw_output TEXT DEFAULT '',
  structured_output TEXT DEFAULT '',
  confidence_score REAL,
  data_sources TEXT DEFAULT ''
);
"""


def _conn() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init() -> None:
    with _conn() as conn:
        conn.executescript(_SCHEMA)


def log_decision(
    stock_code: str,
    analysis_type: str = "技术面",
    model_used: str = "",
    raw_output: str = "",
    structured_output: Any = None,
    *,
    stock_name: str = "",
    confidence_score: float | None = None,
    data_sources: list[str] | str | None = None,
) -> int | None:
    """记录一次 AI 分析。任何异常都不抛出，返回新行 id（失败返回 None）。"""
    try:
        init()
        if isinstance(structured_output, (dict, list)):
            structured_text = json.dumps(structured_output, ensure_ascii=False)
        elif structured_output is None:
            structured_text = ""
        else:
            structured_text = str(structured_output)
        if isinstance(data_sources, (list, tuple)):
            sources_text = ", ".join(str(s) for s in data_sources)
        else:
            sources_text = str(data_sources or "")

        with _conn() as conn:
            cur = conn.execute(
                """INSERT INTO decision_log
                   (timestamp, stock_code, stock_name, model_used, analysis_type,
                    raw_output, structured_output, confidence_score, data_sources)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    now_cn().isoformat(timespec="seconds"),
                    stock_code, stock_name, model_used, analysis_type,
                    raw_output or "", structured_text, confidence_score, sources_text,
                ),
            )
            return int(cur.lastrowid)
    except Exception:  # noqa: BLE001 - 日志模块永不崩溃主流程
        return None


def get_decision_history(stock_code: str | None = None, limit: int = 50) -> list[dict]:
    """查询历史分析记录（最新在前）。"""
    init()
    sql = ("SELECT id, timestamp, stock_code, stock_name, model_used, analysis_type, "
           "confidence_score, data_sources FROM decision_log")
    params: tuple = ()
    if stock_code:
        sql += " WHERE stock_code=?"
        params = (stock_code,)
    sql += " ORDER BY id DESC LIMIT ?"
    params += (int(limit),)
    with _conn() as conn:
        cols = ["id", "timestamp", "stock_code", "stock_name", "model_used",
                "analysis_type", "confidence_score", "data_sources"]
        return [dict(zip(cols, r)) for r in conn.execute(sql, params).fetchall()]


def get_decision_detail(log_id: int) -> dict | None:
    """按 id 取完整记录（含 raw_output / structured_output）。"""
    init()
    with _conn() as conn:
        r = conn.execute("SELECT * FROM decision_log WHERE id=?", (int(log_id),)).fetchone()
        return dict(r) if r else None


def export_decision_log(stock_code: str | None = None, fmt: str = "json") -> str:
    """导出为 JSON 或 CSV 字符串。"""
    init()
    sql = "SELECT * FROM decision_log"
    params: tuple = ()
    if stock_code:
        sql += " WHERE stock_code=?"
        params = (stock_code,)
    sql += " ORDER BY id DESC"
    with _conn() as conn:
        rows = [dict(r) for r in conn.execute(sql, params).fetchall()]

    fmt = (fmt or "json").lower()
    if fmt == "csv":
        buf = io.StringIO()
        cols = ["id", "timestamp", "stock_code", "stock_name", "model_used",
                "analysis_type", "raw_output", "structured_output",
                "confidence_score", "data_sources"]
        w = csv.DictWriter(buf, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in cols})
        return buf.getvalue()

    return json.dumps(rows, ensure_ascii=False, indent=2)
