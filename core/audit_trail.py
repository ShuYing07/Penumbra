# -*- coding: utf-8 -*-
"""合规审计追踪（责任穿透）。

记录每次 AI 分析的完整审计信息：输入摘要（脱敏）、模型、System Prompt 哈希、
合规过滤结果与命中详情。审计只增不改，供事后追溯与人工审查。
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from core.compliance import _FORBIDDEN
from core.config import DATA_DIR, now_cn

_DB = Path(DATA_DIR) / "audit_trail.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_trail(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT,
  input_summary TEXT,
  model_name TEXT,
  system_prompt_hash TEXT,
  filter_result TEXT,
  filter_details TEXT,
  manual_action TEXT
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


def hash_prompt(system_prompt: str) -> str:
    """System Prompt 的 SHA-256 前 16 位（不存原文，仅留指纹）。"""
    return hashlib.sha256((system_prompt or "").encode("utf-8")).hexdigest()[:16]


def analyze_filter(text: str) -> tuple[str, str, list[str]]:
    """对输出做合规分析，返回 (过滤后文本, 结果, 命中词列表)。

    filter_result ∈ {通过, 部分过滤, 拦截}。
    """
    hits = [w for w in _FORBIDDEN if w in (text or "")]
    if not hits:
        return text or "", "通过", []
    filtered = text
    for w in hits:
        filtered = filtered.replace(w, "【已过滤】")
    return filtered, ("拦截" if len(hits) >= 3 else "部分过滤"), hits


def log_audit_entry(input_summary: str,
                     model_name: str,
                     system_prompt: str,
                     filter_result: str,
                     filter_details: list[str] | str,
                     manual_action: str = "") -> int | None:
    try:
        init()
        if isinstance(filter_details, (list, tuple)):
            details_text = ", ".join(str(x) for x in filter_details)
        else:
            details_text = str(filter_details or "")
        summary = (input_summary or "")[:500]
        with _conn() as conn:
            cur = conn.execute(
                """INSERT INTO audit_trail
                   (ts, input_summary, model_name, system_prompt_hash,
                    filter_result, filter_details, manual_action)
                   VALUES (?,?,?,?,?,?,?)""",
                (now_cn().isoformat(timespec="seconds"), summary, model_name,
                 hash_prompt(system_prompt), filter_result, details_text, manual_action),
            )
            return int(cur.lastrowid)
    except Exception:  # noqa: BLE001
        return None


def list_audit(limit: int = 100) -> list[dict]:
    init()
    with _conn() as conn:
        cols = ["id", "ts", "model_name", "system_prompt_hash",
                "filter_result", "filter_details", "manual_action"]
        rows = conn.execute(
            "SELECT * FROM audit_trail ORDER BY id DESC LIMIT ?", (int(limit),)).fetchall()
        return [dict(zip(cols, [r[c] for c in cols])) for r in rows]


def export_audit() -> str:
    init()
    with _conn() as conn:
        rows = [dict(r) for r in conn.execute("SELECT * FROM audit_trail ORDER BY id DESC")]
    return json.dumps(rows, ensure_ascii=False, indent=2)
