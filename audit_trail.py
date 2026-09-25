# -*- coding: utf-8 -*-
"""分析链审计追踪：记录每次分析的完整推理链。"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from datetime import datetime

from core.config import DATA_DIR

log = logging.getLogger("stockai.audit")

_DB = DATA_DIR / "audit.db"


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(str(_DB))
    c.execute("""CREATE TABLE IF NOT EXISTS audit_trail (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        analysis_id TEXT,
        stock_code TEXT,
        input_summary TEXT,
        tools_used TEXT,
        reasoning TEXT,
        conclusion TEXT,
        confidence REAL,
        model TEXT,
        timestamp TEXT
    )""")
    return c


def log_analysis(stock_code: str, input_summary: str, tools_used: list[str],
                 reasoning: str, conclusion: str, confidence: float,
                 model: str) -> str:
    """记录一次完整分析链。返回analysis_id。"""
    analysis_id = f"A{int(time.time())}"
    c = _conn()
    c.execute(
        "INSERT INTO audit_trail (analysis_id,stock_code,input_summary,tools_used,reasoning,conclusion,confidence,model,timestamp) VALUES (?,?,?,?,?,?,?,?,?)",
        (analysis_id, stock_code, input_summary,
         json.dumps(tools_used, ensure_ascii=False),
         reasoning, conclusion, confidence, model,
         datetime.now().isoformat()))
    c.commit()
    c.close()
    log.info("分析链已记录: %s", analysis_id)
    return analysis_id


def get_analysis_chain(analysis_id: str) -> dict | None:
    """获取完整分析链。"""
    c = _conn()
    c.row_factory = sqlite3.Row
    row = c.execute("SELECT * FROM audit_trail WHERE analysis_id=?", (analysis_id,)).fetchone()
    c.close()
    if row:
        return dict(row)
    return None


def list_recent_analyses(limit: int = 20) -> list[dict]:
    """列出最近的分析记录。"""
    c = _conn()
    c.row_factory = sqlite3.Row
    rows = c.execute(
        "SELECT analysis_id,stock_code,conclusion,confidence,model,timestamp FROM audit_trail ORDER BY id DESC LIMIT ?",
        (limit,)).fetchall()
    c.close()
    return [dict(r) for r in rows]
