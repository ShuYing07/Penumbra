# -*- coding: utf-8 -*-
"""用户绘图标注持久化（SQLite）：趋势线/水平线/斐波那契回撤/矩形。

坐标统一存为"全局 K 线索引 + 价格"（与图表窗口无关），换区间/重开
程序均能还原；Agent 工具层通过 list_drawings() 读取用户标注，
在分析中引用（如"你标注的趋势线在 320 附近，当前价已跌破"）。
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from core.config import DATA_DIR

log = logging.getLogger("stockai.drawings")
_DB = DATA_DIR / "drawings.db"
_SCHEMA = """
CREATE TABLE IF NOT EXISTS drawings(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ticker TEXT NOT NULL,
  type TEXT NOT NULL,
  data TEXT NOT NULL,
  created TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_drawings_ticker ON drawings(ticker);
"""


def _conn() -> sqlite3.Connection:
    _DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB))
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def save_drawing(ticker: str, type_: str, points: List[Dict[str, Any]],
                 meta: Dict[str, Any] | None = None) -> int:
    """保存一条绘图。points=[{x,y}, ...]，x 为全局 K 线索引。"""
    try:
        with _conn() as conn:
            cur = conn.execute(
                "INSERT INTO drawings(ticker,type,data,created) VALUES(?,?,?,?)",
                (ticker, type_,
                 json.dumps({"points": points, "meta": meta or {}},
                           ensure_ascii=False),
                 datetime.now().isoformat(timespec="seconds")))
            return int(cur.lastrowid)
    except Exception as e:  # noqa: BLE001
        log.warning("绘图保存失败：%s", e)
        return 0


def list_drawings(ticker: str) -> List[dict]:
    """读取某标的全部绘图（按创建顺序）。"""
    try:
        with _conn() as conn:
            rows = conn.execute(
                "SELECT id,type,data,created FROM drawings WHERE ticker=? ORDER BY id",
                (ticker,)).fetchall()
        out = []
        for r in rows:
            try:
                payload = json.loads(r["data"])
            except Exception:  # noqa: BLE001
                continue
            out.append({"id": r["id"], "type": r["type"], "created": r["created"],
                        "points": payload.get("points", []),
                        "meta": payload.get("meta", {})})
        return out
    except Exception as e:  # noqa: BLE001
        log.warning("绘图读取失败：%s", e)
        return []


def delete_drawing(drawing_id: int) -> bool:
    try:
        with _conn() as conn:
            conn.execute("DELETE FROM drawings WHERE id=?", (drawing_id,))
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("绘图删除失败：%s", e)
        return False


def clear_ticker(ticker: str) -> int:
    try:
        with _conn() as conn:
            cur = conn.execute("DELETE FROM drawings WHERE ticker=?", (ticker,))
        return int(cur.rowcount)
    except Exception as e:  # noqa: BLE001
        log.warning("绘图清空失败：%s", e)
        return 0
