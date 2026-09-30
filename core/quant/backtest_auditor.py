# -*- coding: utf-8 -*-
"""回测审计器（模块三 · 参考 quant-backtest-guard / gobacktest-audit）。

8 条分级审计规则，逐条输出结构化报告 {rule, severity, location, detail}，
另含「诚实结果 vs 被偏差吹大的结果」并排对比与 CI 集成门（严重规则命中即阻止）。

规则清单：
1. lookahead     前视偏差      critical  —— 信号是否用到未来数据
2. time_alignment 时间对齐     critical  —— 时间索引单调/无重复/无未来日期
3. overfit       过拟合        high      —— 样本外年化显著退化
4. cost_neglect  成本忽视      high      —— 含费/不含费收益偏差过大
5. data_snooping 数据窥探      high      —— 全样本参数未做跨期稳健性
6. multi_testing 多重检验      info      —— 多参数组合未校正显著性
7. survivorship  幸存者偏差    info      —— 数据覆盖/存续样本说明
8. liquidity     流动性假设    info      —— 成交额过低时的成交假设提示

全部为客观评估；复用历轮 scan_lookahead / walk_forward / guard_checklist。
"""
from __future__ import annotations

import logging
import math
import os
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

import pandas as pd

from core.quant.audit import scan_lookahead, walk_forward
from core.quant.backtest import run_backtest, BacktestConfig, FeeModel

log = logging.getLogger("stockai.quant.auditor")

_RULES = [
    ("lookahead", "前视偏差", "critical"),
    ("time_alignment", "时间对齐", "critical"),
    ("overfit", "过拟合", "high"),
    ("cost_neglect", "成本忽视", "high"),
    ("data_snooping", "数据窥探", "high"),
    ("multi_testing", "多重检验", "info"),
    ("survivorship", "幸存者偏差", "info"),
    ("liquidity", "流动性假设", "info"),
]


def _check_lookahead(df: pd.DataFrame, strategy: str, params: dict) -> dict:
    la = scan_lookahead(df, strategy, params)
    verdict = la.get("verdict", "na")
    if verdict == "error":
        return {"severity": "critical", "location": "core/quant/audit.py:scan_lookahead",
                "detail": f"前视扫描失败：{la.get('reason', '')}"}
    if verdict == "na":
        return {"severity": "info", "location": "-",
                "detail": f"{la.get('reason', '不适用')}，无需检查"}
    mism = int(la.get("mismatches", 0))
    if mism > 0:
        return {"severity": "critical", "location": f"{strategy} 信号函数",
                "detail": (f"发现 {mism} 个信号点在截断未来数据后不一致"
                           f"（检查 {la.get('checked', 0)} 个）——可能使用了未来数据")}
    return {"severity": "info", "location": f"{strategy} 信号函数",
            "detail": (f"抽查 {la.get('checked', 0)} 个信号点，截断后保持一致"
                       f"（ratio={la.get('ratio', 1):.2f}），无前视偏差")}


def _check_time_alignment(df: pd.DataFrame) -> dict:
    if df is None or len(df) == 0:
        return {"severity": "critical", "location": "data_fetcher",
                "detail": "数据为空，无法审计"}
    idx = df.index
    if not isinstance(idx, pd.DatetimeIndex):
        return {"severity": "info", "location": "index",
                "detail": "非时间索引，时间对齐检查跳过"}
    dup = int(idx.duplicated().sum())
    monotonic = bool(idx.is_monotonic_increasing)
    future = bool(idx.max() > pd.Timestamp(datetime.now().date()))
    problems = []
    if dup:
        problems.append(f"{dup} 个重复时间戳")
    if not monotonic:
        problems.append("时间索引非单调递增")
    if future:
        problems.append(f"含未来日期（{idx.max().date()}）")
    if problems:
        return {"severity": "critical", "location": "index",
                "detail": "时间对齐异常：" + "；".join(problems)}
    return {"severity": "info", "location": "index",
            "detail": f"时间索引单调无重复，共 {len(idx)} 根，截至 {idx.max().date()}"}


def _check_overfit(df: pd.DataFrame, strategy: str, params: dict) -> dict:
    try:
        wf = walk_forward(df, in_ratio=0.6)
    except Exception as e:  # noqa: BLE001
        return {"severity": "high", "location": "walk_forward",
                "detail": f"样本外验证不可计算：{e}"}
    oos_ret = float((wf.get("oos") or {}).get("annual_return", 0.0) or 0.0)
    in_ret = float((wf.get("in") or {}).get("annual_return", 0.0) or 0.0)
    if in_ret > 0 and oos_ret < 0:
        return {"severity": "high", "location": f"{strategy} 参数 {params}",
                "detail": f"样本内 {in_ret:.1%} 为正、样本外 {oos_ret:.1%} 转负——过拟合风险"}
    if oos_ret < in_ret * 0.5:
        return {"severity": "high", "location": f"{strategy} 参数 {params}",
                "detail": f"样本外 {oos_ret:.1%} 显著低于样本内 {in_ret:.1%}"}
    return {"severity": "info", "location": f"{strategy}",
            "detail": f"样本内 {in_ret:.1%} / 样本外 {oos_ret:.1%}，无显著退化"}


def _check_cost_neglect(df: pd.DataFrame, market: str, strategy: str,
                        params: dict) -> dict:
    """含费 vs 不含费收益并排（诚实 vs 偏差）。"""
    try:
        honest = run_backtest(df, market, strategy, params,
                              BacktestConfig(market=market))
        no_fee_cfg = BacktestConfig(market=market)
        no_fee_cfg.fee_rate = 0.0
        no_fee_cfg.stamp_duty = 0.0
        no_fee_cfg.slippage = 0.0
        biased = run_backtest(df, market, strategy, params, no_fee_cfg)
        h_ret = float(honest.metrics.get("total_return_pct", 0.0) or 0.0) / 100.0
        b_ret = float(biased.metrics.get("total_return_pct", 0.0) or 0.0) / 100.0
        if not (math.isfinite(h_ret) and math.isfinite(b_ret)):
            return {"severity": "info", "location": "cost_neglect",
                    "detail": "回测无有效交易或收益指标不可计算，成本对比跳过"}
        gap = abs(b_ret - h_ret) / max(abs(h_ret), 1e-9)
        if gap > 0.2 and abs(h_ret) > 1e-6:
            return {"severity": "high", "location": "BacktestConfig(fee/slippage)",
                    "detail": (f"含费收益 {h_ret:.1%} vs 不含费 {b_ret:.1%}，"
                               f"偏差 {gap:.0%}——忽视成本会显著高估策略")}
        return {"severity": "info", "location": "BacktestConfig",
                "detail": f"含费 {h_ret:.1%} / 不含费 {b_ret:.1%}，成本影响 {gap:.0%}"}
    except Exception as e:  # noqa: BLE001
        return {"severity": "high", "location": "cost_neglect",
                "detail": f"成本对比不可计算：{e}"}


def _check_data_snooping(strategy: str, params: dict, df: pd.DataFrame) -> dict:
    if not params:
        return {"severity": "info", "location": "-",
                "detail": "未使用显式参数，数据窥探风险低"}
    # 代理：常见参数区间外 → 提示可能为全样本搜索痕迹
    extremes = []
    for k, v in params.items():
        if isinstance(v, (int, float)):
            if v > 500 or (isinstance(v, float) and v > 0.9):
                extremes.append(f"{k}={v}")
    if extremes:
        return {"severity": "high", "location": f"params {params}",
                "detail": f"参数 {extremes} 落在常见区间外，疑似在全样本上搜索得到——需跨期稳健性检验"}
    return {"severity": "info", "location": f"params {params}",
            "detail": "参数在常规区间内；建议再做跨期滚动稳健性检验"}


def _check_multi_testing(strategy: str, params: dict) -> dict:
    if not params:
        return {"severity": "info", "location": "-",
                "detail": "单组参数，无多重检验负担"}
    n = len(params)
    if n >= 3:
        return {"severity": "info", "location": f"params({n} 维)",
                "detail": f"{n} 维参数组合存在多重检验风险，未做 Bonferroni 等显著性校正；实盘前建议降维或校正"}
    return {"severity": "info", "location": f"params({n} 维)",
            "detail": f"{n} 维参数，多重检验负担较低"}


def _check_survivorship(df: pd.DataFrame) -> dict:
    if df is None or len(df) == 0:
        return {"severity": "info", "location": "-", "detail": "无数据"}
    n = len(df)
    if n < 250:
        return {"severity": "info", "location": "data_fetcher",
                "detail": f"样本仅 {n} 根日线（<1 年），覆盖不足；且使用当前存续标的，未含已退市标的"}
    return {"severity": "info", "location": "data_fetcher",
            "detail": f"样本 {n} 根日线；注意仅覆盖存续标的（幸存者偏差无法完全排除）"}


def _check_liquidity(df: pd.DataFrame) -> dict:
    if df is None or "volume" not in df.columns:
        return {"severity": "info", "location": "-", "detail": "无成交量数据，流动性假设检查跳过"}
    try:
        avg_v = float(df["volume"].mean())
        med_v = float(df["volume"].median())
    except Exception:  # noqa: BLE001
        return {"severity": "info", "location": "volume", "detail": "成交量不可解析"}
    if med_v < 1e5:
        return {"severity": "info", "location": "volume",
                "detail": f"日均成交量 {avg_v:.0f} / 中位 {med_v:.0f}，流动性偏低——回测假设的成交价在实盘可能无法实现"}
    return {"severity": "info", "location": "volume",
            "detail": f"日均成交量 {avg_v:.0f}，流动性假设基本成立"}


def audit_strategy(df: pd.DataFrame, market: str = "CN",
                   strategy: str = "ma_cross",
                   params: Optional[Dict[str, Any]] = None) -> dict:
    """对策略执行 8 条分级审计。返回结构化报告。"""
    params = dict(params or {})
    checks: List[dict] = []
    checks.append({"rule": "lookahead", "name": "前视偏差",
                   **_check_lookahead(df, strategy, params)})
    checks.append({"rule": "time_alignment", "name": "时间对齐",
                   **_check_time_alignment(df)})
    checks.append({"rule": "overfit", "name": "过拟合",
                   **_check_overfit(df, strategy, params)})
    checks.append({"rule": "cost_neglect", "name": "成本忽视",
                   **_check_cost_neglect(df, market, strategy, params)})
    checks.append({"rule": "data_snooping", "name": "数据窥探",
                   **_check_data_snooping(strategy, params, df)})
    checks.append({"rule": "multi_testing", "name": "多重检验",
                   **_check_multi_testing(strategy, params)})
    checks.append({"rule": "survivorship", "name": "幸存者偏差",
                   **_check_survivorship(df)})
    checks.append({"rule": "liquidity", "name": "流动性假设",
                   **_check_liquidity(df)})

    critical = sum(1 for c in checks if c["severity"] == "critical")
    high = sum(1 for c in checks if c["severity"] == "high")
    score = max(0, min(100, 100 - critical * 25 - high * 10))
    grade = ("D" if critical else "C" if high else "B") if (critical or high) else "A"
    passed = critical == 0 and high == 0
    return {"grade": grade, "score": score, "passed": passed,
            "checks": checks,
            "summary": f"审计 {grade} 级 · {score}/100 · 致命 {critical} / 高危 {high}"}


def honest_vs_biased(df: pd.DataFrame, market: str = "CN",
                     strategy: str = "ma_cross",
                     params: Optional[Dict[str, Any]] = None) -> dict:
    """「诚实结果」与「被偏差吹大的结果」并排展示（成本/前视两维度）。"""
    params = dict(params or {})
    out: Dict[str, Any] = {}
    # 成本维度
    try:
        honest = run_backtest(df, market, strategy, params,
                              BacktestConfig(market=market))
        zero_fee = FeeModel(commission_rate=0.0, min_commission=0.0,
                            stamp_tax_sell=0.0, transfer_fee=0.0,
                            slippage_bps=0.0)
        biased = run_backtest(df, market, strategy, params,
                              BacktestConfig(market=market, fee=zero_fee))
        h_ret = float(honest.metrics.get("total_return_pct", 0.0) or 0.0) / 100.0
        b_ret = float(biased.metrics.get("total_return_pct", 0.0) or 0.0) / 100.0
        if not math.isfinite(h_ret):
            h_ret = None
        if not math.isfinite(b_ret):
            b_ret = None
        out["cost"] = {
            "label": "成本维度（诚实=含费 / 偏差=零成本）",
            "honest": {"total_return": (round(h_ret * 100, 2)
                                        if h_ret is not None else None),
                       "max_drawdown": round(float(honest.metrics.get("max_drawdown_pct", 0) or 0), 2),
                       "sharpe": round(float(honest.metrics.get("sharpe", 0) or 0), 3)},
            "biased": {"total_return": (round(b_ret * 100, 2)
                                        if b_ret is not None else None),
                       "max_drawdown": round(float(biased.metrics.get("max_drawdown_pct", 0) or 0), 2),
                       "sharpe": round(float(biased.metrics.get("sharpe", 0) or 0), 3)},
        }
    except Exception as e:  # noqa: BLE001
        out["cost"] = {"error": str(e)}
    # 前视维度：含费完整回测 vs 抽样剔除异常（前视扫描的 mismatch 数）
    la = scan_lookahead(df, strategy, params)
    out["lookahead"] = {
        "label": "前视维度（诚实=截断重算 / 偏差=全量信号）",
        "honest": {"mismatches": int(la.get("mismatches", 0)),
                   "verdict": la.get("verdict", "na")},
        "biased": {"signals_used": "全部历史信号（未截断）"},
    }
    return out


def audit_ci(df: pd.DataFrame, market: str = "CN",
             strategy: str = "ma_cross",
             params: Optional[Dict[str, Any]] = None,
             blocking_on: tuple = ("critical", "high")) -> dict:
    """CI 集成门：严重规则命中 → 阻止进入实盘。"""
    report = audit_strategy(df, market, strategy, params)
    blocked = [c for c in report["checks"]
               if c["severity"] in blocking_on]
    return {"block": bool(blocked), "blocked_rules": blocked,
            "report": report}


if __name__ == "__main__":
    import numpy as np
    rng = np.random.default_rng(11)
    close = pd.Series(100 * np.cumprod(1 + rng.normal(0.001, 0.02, 400)))
    bars = pd.DataFrame({"open": close, "high": close * 1.01,
                         "low": close * 0.99, "close": close,
                         "volume": rng.integers(1e5, 5e5, 400)},
                        index=pd.date_range("2024-01-01", periods=400))
    r = audit_strategy(bars, "CN", "ma_cross", {"fast": 5, "slow": 20})
    assert len(r["checks"]) == 8
    assert r["grade"] in ("A", "B", "C", "D")
    assert r["score"] >= 0
    assert all(set(c) >= {"rule", "name", "severity", "detail"} for c in r["checks"])
    hb = honest_vs_biased(bars, "CN", "ma_cross", {"fast": 5, "slow": 20})
    assert "cost" in hb and "lookahead" in hb
    ci = audit_ci(bars, "CN", "ma_cross", {"fast": 5, "slow": 20})
    assert "block" in ci and "blocked_rules" in ci
    # 时间对齐异常应命中 critical
    bad_idx = pd.date_range("2026-01-01", periods=20).append(
        pd.date_range("2025-01-01", periods=10))
    bad = bars.iloc[:30].copy()
    bad.index = bad_idx
    ta = _check_time_alignment(bad)
    assert ta["severity"] == "critical", ta
    print(f"backtest_auditor self-check ok ({r['grade']}/{r['score']} · "
          f"cost_gap={hb['cost']['honest']['total_return']} vs "
          f"{hb['cost']['biased']['total_return']})")
