# -*- coding: utf-8 -*-
"""案例记忆（Case-Based Memory）：检索历史相似情境，辅助当前决策。

核心思想：遇到新分析任务时，检索过去处理过的相似案例（同行业/同形态/同市场状态），
参考之前的决策路径和实际结果，注入当前分析上下文。
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass

import numpy as np

from core.data.cache import get_conn

log = logging.getLogger("stockai.case_memory")


@dataclass
class SimilarCase:
    """一个历史相似案例。"""
    decision_id: int
    ticker: str
    asof: str
    market_regime: str
    action: str
    confidence: int
    summary: str
    realized_return_pct: float | None
    reflection: str
    similarity_score: float


def _ensure_table():
    """确保有一个案例特征表（从decisions表派生）。"""
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS case_features(
              decision_id INTEGER PRIMARY KEY,
              ticker TEXT,
              asof TEXT,
              regime TEXT,
              rsi_14 REAL,
              vol_ratio REAL,
              ma_position REAL,
              momentum_20d REAL,
              action TEXT,
              confidence INTEGER,
              realized_return_pct REAL
            )
        """)


def extract_features(state: dict) -> dict:
    """从当前分析状态提取特征向量，用于相似度匹配。"""
    tech = state.get("tech", {})
    regime = state.get("regime", {})
    return {
        "regime": regime.get("regime", "range"),
        "rsi_14": tech.get("rsi_14", 50),
        "vol_ratio": tech.get("vol_ratio_5_20", 1.0),
        "ma_position": tech.get("pos_in_60d_pct", 50),
        "momentum_20d": tech.get("chg_pct_periods", {}).get("20d", 0),
    }


def save_case(decision_id: int, state: dict, realized_return: float | None = None):
    """把一次分析的特征存入案例库。"""
    _ensure_table()
    feat = extract_features(state)
    with get_conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO case_features
               (decision_id, ticker, asof, regime, rsi_14, vol_ratio, ma_position, momentum_20d,
                action, confidence, realized_return_pct)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (decision_id, state.get("ticker", ""), state.get("asof", ""),
             feat["regime"], feat["rsi_14"], feat["vol_ratio"],
             feat["ma_position"], feat["momentum_20d"],
             (state.get("final") or {}).get("action", ""),
             (state.get("final") or {}).get("confidence", 50),
             realized_return))


def find_similar_cases(state: dict, n: int = 5) -> list[SimilarCase]:
    """找与当前状态最相似的历史案例。

    相似度：归一化特征距离（欧氏距离的反向）。
    """
    _ensure_table()
    feat = extract_features(state)

    with get_conn() as conn:
        rows = conn.execute("""
            SELECT decision_id, ticker, asof, regime, rsi_14, vol_ratio,
                   ma_position, momentum_20d, action, confidence, realized_return_pct
            FROM case_features
            WHERE realized_return_pct IS NOT NULL
            ORDER BY decision_id DESC LIMIT 500
        """).fetchall()

    if not rows:
        return []

    # 归一化特征距离
    def _dist(r):
        # rsi, vol_ratio, ma_position, momentum_20d
        d_rsi = abs((r[4] or 50) - feat["rsi_14"]) / 50.0
        d_vol = abs((r[5] or 1.0) - feat["vol_ratio"]) / 2.0
        d_ma = abs((r[6] or 50) - feat["ma_position"]) / 50.0
        d_mom = abs((r[7] or 0) - feat["momentum_20d"]) / 20.0
        return (d_rsi + d_vol + d_ma + d_mom) / 4.0

    scored = sorted(rows, key=_dist)[:n]
    cases = []
    for r in scored:
        dist = _dist(r)
        cases.append(SimilarCase(
            decision_id=r[0], ticker=r[1], asof=r[2],
            market_regime=r[3], action=r[8], confidence=r[9],
            summary="", realized_return_pct=r[10], reflection="",
            similarity_score=round(1.0 - dist, 3),
        ))
    return cases


def cases_to_context(cases: list[SimilarCase]) -> list[dict]:
    """把相似案例转成prompt可用的上下文。"""
    return [{
        "相似案例": f"#{c.decision_id} {c.ticker} ({c.asof[:10] if c.asof else ''})",
        "当时判断": c.action,
        "实际涨跌%": c.realized_return_pct,
        "相似度": c.similarity_score,
    } for c in cases]
