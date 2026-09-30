# -*- coding: utf-8 -*-
"""评测套件与历史趋势（模块一 · 参考 FORCE-Bench / FinToolBench）。

- STANDARD_CASES：标准测试用例（分析茅台技术面 / 对比宁德与比亚迪 / …），
  每例含 query、reference 关键数值、期望得分下限；
- run_suite(evaluator)：对每个用例跑八维评测，返回逐例评分；
- 评分记录持久化到 SQLite（eval_history 表），可查询历史趋势；
- best_case：把多个输出并排比较，供「AI 升级后自动评测」使用。
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import sys
import time
from contextlib import contextmanager
from typing import Any, Callable, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from core.eval.eval_benchmark import evaluate_analysis
from core.config import DATA_DIR

log = logging.getLogger("stockai.core.eval.suite")

_DB = DATA_DIR / "eval_history.db"
_SCHEMA = """
CREATE TABLE IF NOT EXISTS eval_history(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts REAL, case_id TEXT, query TEXT, total REAL, verdict TEXT,
  scores TEXT, version TEXT
);
"""

STANDARD_CASES: List[Dict[str, Any]] = [
    {"id": "maotai_technical", "query": "分析茅台技术面",
     "reference": {"close": 320.5, "rsi14": 62.9, "pe": 28.0},
     "min_total": 0.55},
    {"id": "catl_vs_byd", "query": "对比宁德时代和比亚迪",
     "reference": {"catl_pe": 30.0, "byd_pe": 25.0, "catl_margin": 0.18},
     "min_total": 0.5},
    {"id": "risk_assessment", "query": "这只股票有什么风险",
     "reference": {"max_drawdown": -0.25, "vol": 0.35},
     "min_total": 0.5},
    {"id": "backtest_interpret", "query": "解释这个回测结果",
     "reference": {"total_return": 0.12, "max_drawdown": -0.08},
     "min_total": 0.5},
]


def _conn() -> sqlite3.Connection:
    _DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB))
    conn.executescript(_SCHEMA)
    return conn


@contextmanager
def _db():
    c = _conn()
    try:
        yield c
        c.commit()
    finally:
        c.close()


def run_case(text: str, case: Dict[str, Any]) -> dict:
    """对单个标准用例打分。"""
    r = evaluate_analysis(text, case["query"], case.get("reference") or {})
    return {"case_id": case["id"], "query": case["query"],
            "total": r["total"], "verdict": r["verdict"],
            "scores": r["scores"], "pass": r["total"] >= case.get("min_total", 0.5)}


def run_suite(texts: Optional[Dict[str, str]] = None,
              version: str = "dev") -> List[dict]:
    """跑完整套件并记录历史。texts: {case_id: analysis_text}，缺省空文本。"""
    results: List[dict] = []
    for case in STANDARD_CASES:
        text = (texts or {}).get(case["id"], "")
        res = run_case(text, case)
        results.append(res)
        _record(res, version)
    return results


def _record(res: dict, version: str) -> None:
    try:
        with _db() as conn:
            conn.execute(
                "INSERT INTO eval_history(ts,case_id,query,total,verdict,scores,version)"
                " VALUES(?,?,?,?,?,?,?)",
                (time.time(), res["case_id"], res["query"], res["total"],
                 res["verdict"], json.dumps(res["scores"], ensure_ascii=False),
                 version))
    except Exception as e:  # noqa: BLE001
        log.debug("评测记录失败：%s", e)


def history(case_id: Optional[str] = None, limit: int = 100) -> List[dict]:
    """历史评分趋势（按时间正序）。"""
    try:
        sql = ("SELECT ts,case_id,query,total,verdict,scores,version "
               "FROM eval_history")
        params: tuple = ()
        if case_id:
            sql += " WHERE case_id=?"
            params = (case_id,)
        sql += " ORDER BY ts DESC LIMIT ?"
        with _db() as conn:
            rows = conn.execute(sql, params + (limit,)).fetchall()
        return [{"ts": r[0], "case_id": r[1], "query": r[2], "total": r[3],
                 "verdict": r[4], "scores": json.loads(r[5] or "{}"),
                 "version": r[6]} for r in rows]
    except Exception as e:  # noqa: BLE001
        log.debug("评测历史读取失败：%s", e)
        return []


def best_case(texts: Dict[str, str], case_id: str = "maotai_technical") -> dict:
    """多个输出并排比较（AI 升级前后对比用）。"""
    case = next((c for c in STANDARD_CASES if c["id"] == case_id), STANDARD_CASES[0])
    scored = [{"label": label, **run_case(text, case)}
              for label, text in texts.items()]
    scored.sort(key=lambda s: s["total"], reverse=True)
    return {"case": case_id, "ranked": scored,
            "best": scored[0] if scored else None}


if __name__ == "__main__":
    good_texts = {
        "maotai_technical": ("### 摘要\n结论：RSI(14)=62.9 中性偏强。\n"
                             "数据来源：AKShare日线，获取于 2026-09-28。\n"
                             "风险：PE 28 偏高，支撑 310。"),
        "catl_vs_byd": ("宁德PE 30 vs 比亚迪PE 25，宁德毛利率 18%。\n"
                        "数据来源：2026Q2财报。结论：估值有差异。"),
        "risk_assessment": ("最大回撤 -25%，波动率 35%。\n"
                            "来源：回测数据，2025-01 至 2026-09。\n风险偏高。"),
        "backtest_interpret": ("### 回测解读\n总收益 12%，最大回撤 -8%。\n"
                               "数据来源：回测日志（2025-01 至 2026-09）。\n"
                               "结论：策略在样本外有效，Sharpe 稳定。"),
    }
    r = run_suite(good_texts, version="selfcheck")
    assert len(r) == 4
    assert all(x["pass"] for x in r), [(x["case_id"], x["total"]) for x in r]
    h = history(limit=10)
    assert h and h[0]["version"] == "selfcheck"
    cmp = best_case({"旧模型": "还行吧", "新模型": good_texts["maotai_technical"]})
    assert cmp["ranked"][0]["label"] == "新模型"
    print(f"eval_suite self-check ok ({len(r)} cases all pass)")
