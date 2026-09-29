# -*- coding: utf-8 -*-
"""数据质量与校验（任务书A·模块二）。

参考 FinReg-Validator（监管报送数据质量自动检查）与 Ibis Profiling（缺失值/异常值/
分布偏斜剖析）的设计，对行情 OHLCV 与财报摘要做可量化校验：

- validate_stock_data(df)：
  · 缺失值检查（open/high/low/close/volume 是否含 NaN/None）
  · 异常值检查（价格≤0；单日波动 >50% 的极端跳变）
  · 时间连续性检查（交易日缺口，容忍周末与法定节假日）
  · 输出 {passed, issues, checks, score}，score=100 起按问题类型扣分
- validate_financial_report(report)：
  · 关键字段存在性（营收/净利润/毛利率）
  · 数值合理性（营收>0、毛利率 0~100%）
  · 多期一致性（报告期存在且按时间排序）
- save_quality_report / get_quality_report：质量报告落 SQLite（quality_reports 表）
- fetch_and_check(ticker)：联网/缓存取数 → 校验 → 报告（供 UI「数据质量」页与 Agent 工具调用）

全部为客观统计，不构成投资建议。
"""
from __future__ import annotations

import json
import logging
import math
import os
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from core.data.cache import get_conn

log = logging.getLogger("stockai.data_quality")

_OHLCV = ("open", "high", "low", "close", "volume")
_JUMP_LIMIT = 50.0          # 单日涨跌幅绝对值 >50% 视为可疑（正常股票罕见）
_MIN_SCORE_PASS = 70.0      # 及格线


def validate_stock_data(df) -> Dict[str, object]:
    """校验日线 OHLCV 数据质量。

    返回 {passed, issues, checks, score, rows}。
    """
    issues: List[str] = []
    checks: Dict[str, object] = {}
    if df is None or len(df) == 0:
        return {"passed": False, "issues": ["数据为空"], "checks": {},
                "score": 0.0, "rows": 0}

    rows = len(df)
    score = 100.0

    # 1) 必需列
    missing_cols = [c for c in _OHLCV if c not in df.columns]
    if missing_cols:
        issues.append(f"缺少必需列: {missing_cols}")
        return {"passed": False, "issues": issues, "checks": {"missing_cols": missing_cols},
                "score": 0.0, "rows": rows}

    # 2) 缺失值
    na_counts = {c: int(df[c].isna().sum()) for c in _OHLCV}
    na_total = sum(na_counts.values())
    checks["na_counts"] = na_counts
    if na_total > 0:
        score -= min(40.0, na_total * 2.0)
        issues.append(f"存在 {na_total} 个缺失值: {na_counts}")

    # 3) 非正价格
    bad_price = int((df["close"] <= 0).sum())
    checks["nonpositive"] = bad_price
    if bad_price > 0:
        score -= min(20.0, bad_price * 2.0)
        issues.append(f"{bad_price} 行收盘价<=0")

    # 4) 极端单日波动（close 与 high/low 两口径）
    close_chg = df["close"].pct_change().abs() * 100.0
    jumps_close = int((close_chg > _JUMP_LIMIT).sum())
    hl_ratio = (df["high"] / df["low"].replace(0, np.nan)).abs()
    jumps_hl = int((hl_ratio > (1 + _JUMP_LIMIT / 100.0)).sum())
    checks["jumps_close"] = jumps_close
    checks["jumps_hl"] = jumps_hl
    n_jump = jumps_close + jumps_hl
    if n_jump > 0:
        score -= min(30.0, n_jump * 5.0)
        issues.append(f"{n_jump} 处单日波动超过 50%（close 口径 {jumps_close}，high/low 口径 {jumps_hl}）")

    # 5) 时间连续性（交易日缺口：间隔>7 自然日视为异常，容忍长假）
    gap_days = 0
    if isinstance(df.index, pd.DatetimeIndex) and len(df) >= 2:
        d = df.index.to_series().diff().dt.days
        big = d[d > 7]
        gap_days = int((big / 7).sum())
        checks["gap_days"] = gap_days
        if gap_days > 0:
            score -= min(10.0, gap_days * 5.0)
            issues.append(f"存在 {gap_days} 处交易日缺口（间隔>7天）")

    checks["rows"] = rows
    passed = score >= _MIN_SCORE_PASS and not missing_cols
    return {
        "passed": passed,
        "issues": issues,
        "checks": checks,
        "score": round(score, 1),
        "rows": rows,
    }


def validate_financial_report(report: Dict[str, object]) -> Dict[str, object]:
    """校验财报摘要的完整性与数值合理性。

    report 字段（来自 financial_report_parser / get_financial_reports）：
      period / revenue / net_profit / gross_margin / 可选 roe / revenue_yoy ...
    """
    issues: List[str] = []
    score = 100.0
    if not report:
        return {"passed": False, "issues": ["财报数据为空"], "checks": {}, "score": 0.0}

    # 1) 关键字段
    for key, label in (("revenue", "营收"), ("net_profit", "净利润"), ("gross_margin", "毛利率")):
        v = report.get(key)
        if v is None or str(v).strip() in ("", "-", "nan", "None"):
            score -= 25.0
            issues.append(f"缺少{label}字段")

    def _num(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    # 2) 数值合理性
    rev = _num(report.get("revenue"))
    if rev is not None and rev <= 0:
        score -= 15.0
        issues.append("营收<=0（异常）")
    gm = _num(report.get("gross_margin"))
    if gm is not None and not (0.0 <= gm <= 100.0):
        score -= 10.0
        issues.append("毛利率超出 0~100% 区间")

    # 3) 多期一致性（period 非空即通过；排序性由调用方多期列表校验）
    if not str(report.get("period") or "").strip():
        score -= 10.0
        issues.append("缺少报告期")
    checks = {"fields": [k for k in ("period", "revenue", "net_profit", "gross_margin")
                         if report.get(k) is not None]}
    return {"passed": score >= _MIN_SCORE_PASS, "issues": issues,
            "checks": checks, "score": round(max(score, 0.0), 1)}


def validate_report_series(reports: List[dict]) -> Dict[str, object]:
    """多期财报一致性：报告期按时间升序且无倒挂。"""
    issues: List[str] = []
    if not reports:
        return {"passed": True, "issues": [], "checks": {}, "score": 100.0}
    periods = [r.get("period") for r in reports if r.get("period")]
    if len(periods) < 2:
        return {"passed": True, "issues": [], "checks": {"periods": len(periods)}, "score": 100.0}
    # 报告期形如 2026-06-30 / 20260331 / 2026年06月 → 转可排序数值
    def _ts(p):
        s = str(p)
        s = s.replace("年", "-").replace("月", "-").replace("日", "")
        import re
        m = re.findall(r"\d{4}[-/]?\d{1,2}[-/]?\d{1,2}", s)
        if not m:
            return None
        t = re.sub(r"[-/]", "", m[0])
        try:
            return int(t.ljust(8, "0"))
        except ValueError:
            return None
    ts = [_ts(p) for p in periods]
    valid = [t for t in ts if t is not None]
    if valid and valid != sorted(valid):
        issues.append("多期报告期存在倒挂/乱序")
        return {"passed": False, "issues": issues, "checks": {"periods": periods},
                "score": 60.0}
    return {"passed": True, "issues": issues, "checks": {"periods": periods}, "score": 100.0}


# ---------------------------------------------------------------------------
# 质量报告持久化（SQLite quality_reports）
# ---------------------------------------------------------------------------

def _schema() -> str:
    return """
CREATE TABLE IF NOT EXISTS quality_reports(
  ticker TEXT PRIMARY KEY,
  report TEXT NOT NULL,
  fetched_at TEXT NOT NULL
);
"""


def save_quality_report(ticker: str, report: Dict[str, object]) -> None:
    from core.config import now_cn
    with get_conn() as conn:
        conn.execute(_schema())
        conn.execute(
            "INSERT OR REPLACE INTO quality_reports(ticker, report, fetched_at)"
            " VALUES (?,?,?)",
            (ticker, json.dumps(report, ensure_ascii=False),
             now_cn().isoformat(timespec="seconds")),
        )


def get_quality_report(ticker: str) -> Optional[Dict[str, object]]:
    with get_conn() as conn:
        conn.execute(_schema())
        row = conn.execute(
            "SELECT report, fetched_at FROM quality_reports WHERE ticker=?",
            (ticker,)).fetchone()
    if not row:
        return None
    out = json.loads(row[0])
    out["fetched_at"] = row[1]
    return out


def fetch_and_check(ticker: str, use_cache: bool = True) -> Dict[str, object]:
    """取数 → 校验 → 落库 → 返回质量报告（UI / Agent 工具统一入口）。

    返回 {ok, ticker, score, passed, issues, checks, rows, source, fetched_at}。
    """
    from core.data.service import get_daily
    try:
        df, source = get_daily(ticker, use_cache=use_cache)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "ticker": ticker, "score": 0.0, "passed": False,
                "issues": [f"取数失败: {type(e).__name__}: {e}"], "checks": {},
                "rows": 0, "source": "error", "fetched_at": None}
    q = validate_stock_data(df)
    q["source"] = source
    q["ticker"] = ticker
    save_quality_report(ticker, q)
    q["ok"] = bool(df is not None and len(df) > 0)
    q["fetched_at"] = q.get("fetched_at")
    return q
