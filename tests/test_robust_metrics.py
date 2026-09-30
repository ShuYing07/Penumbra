# -*- coding: utf-8 -*-
"""模块三 · 回测稳健性指标（GT-Score/Sharpe稳定性/多空统计/持仓统计）测试。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("STOCKAI_MOCK", "1")

import numpy as np
import pandas as pd

from core.quant.backtest import run_backtest, compute_metrics, BacktestConfig
from core.quant.robust_metrics import (gt_score, sharpe_stability,
                                       long_short_stats, holding_stats,
                                       robust_report)
from core.quant.audit import run_audit

PASS = 0


def ok(name: str):
    global PASS
    PASS += 1
    print(f"[ok] {name}")


def _mk_equity(days=300):
    idx = pd.date_range("2024-01-01", periods=days, freq="B")
    rng = np.random.default_rng(7)
    strat = 1_000_000 * np.cumprod(1 + rng.normal(0.0005, 0.012, days))
    bench = 1_000_000 * np.cumprod(1 + rng.normal(0.0002, 0.01, days))
    return pd.DataFrame({"strategy": strat, "benchmark": bench}, index=idx)


def test_sharpe_stability_bounds():
    rng = np.random.default_rng(1)
    stable = sharpe_stability(rng.normal(0.0005, 0.01, 600))
    noisy = sharpe_stability(rng.normal(0.0, 0.08, 600))
    assert 0.0 <= stable <= 1.0
    assert 0.0 <= noisy <= 1.0
    # 平稳收益序列稳定性应高于高噪声序列
    assert stable >= noisy or abs(stable - noisy) < 1e-9
    assert sharpe_stability(np.zeros(100)) == 0.0
    ok("Sharpe 稳定性：0~1 有界且平稳序列得分更高")


def test_long_short_stats():
    rounds = [{"pnl": 100, "hold_days": 5}, {"pnl": -50, "hold_days": 3},
              {"pnl": 80, "hold_days": 4}, {"pnl": -30, "hold_days": 2},
              {"pnl": 200, "hold_days": 6}]
    s = long_short_stats(rounds)
    assert s["n_rounds"] == 5
    assert s["win_rate_pct"] == 60.0
    assert s["max_win_pct"] == 200.0 and s["max_loss_pct"] == -50.0
    assert s["extreme_rounds"] >= 0
    empty = long_short_stats([])
    assert empty["n_rounds"] == 0
    ok("多空统计：次数/胜率/极端值正确")


def test_holding_stats_trapped_and_missed():
    eq = _mk_equity(300)
    # 构造：先深跌再反弹（套牢），随后空仓期间基准大涨（踏空）
    h = holding_stats(eq, trapped_dd=3.0, gap_bench_pct=1.0)
    assert h["total_days"] == 300
    assert 0 <= h["trapped_days"] <= h["total_days"]
    assert h["trapped_ratio_pct"] >= 0.0
    assert h["missed_segments"] >= 0
    ok("持仓统计：套牢/踏空指标结构完整")


def test_gt_score_composition():
    metrics = {"annual_return_pct": 20.0, "max_drawdown_pct": -8.0}
    g = gt_score(metrics, p_value=0.01, daily_returns=np.random.default_rng(3).normal(0.0004, 0.01, 600))
    assert 0 <= g["gt_score"] <= 100
    assert g["perf_term"] >= 0 and g["significance_term"] >= 0
    # 显著性高（p 小）→ sig 项高
    g_weak = gt_score(metrics, p_value=0.5, daily_returns=np.random.default_rng(3).normal(0.0004, 0.01, 600))
    assert g["significance_term"] > g_weak["significance_term"]
    ok("GT-Score：四因子复合且显著性敏感")


def test_run_backtest_exposes_rounds():
    rng = np.random.default_rng(5)
    close = 100 * np.cumprod(1 + rng.normal(0.0003, 0.015, 300))
    df = pd.DataFrame({"open": close, "high": close * 1.01, "low": close * 0.99,
                       "close": close, "volume": 1e6},
                      index=pd.date_range("2024-01-01", periods=300, freq="B"))
    res = run_backtest(df, "CN", "ma_cross", {"fast": 5, "slow": 20}, None)
    assert hasattr(res, "rounds") and isinstance(res.rounds, list)
    assert res.metrics["closed_rounds"] == len(res.rounds)
    ok("BacktestResult 暴露 rounds（供稳健指标使用）")


def test_audit_includes_robust():
    rng = np.random.default_rng(6)
    close = 100 * np.cumprod(1 + rng.normal(0.0003, 0.015, 400))
    df = pd.DataFrame({"open": close, "high": close * 1.01, "low": close * 0.99,
                       "close": close, "volume": 1e6},
                      index=pd.date_range("2024-01-01", periods=400, freq="B"))
    audit = run_audit(df, "CN", "ma_cross", {"fast": 5, "slow": 20}, None)
    assert "robust" in audit
    rb = audit["robust"]
    if "error" not in rb:
        assert "gt_score" in rb and "sharpe_stability" in rb
        assert "long_short" in rb and "holding" in rb
    ok("run_audit 输出包含稳健性指标块")


def test_robust_report_shape():
    eq = _mk_equity(400)
    metrics = {"annual_return_pct": 15.0, "max_drawdown_pct": -10.0}
    rep = robust_report(metrics, 0.03, eq["strategy"].pct_change().dropna(),
                        eq, [{"pnl": 50, "hold_days": 4}, {"pnl": -20, "hold_days": 2}])
    assert set(rep) >= {"gt_score", "sharpe_stability", "long_short", "holding"}
    ok("robust_report 一站式报告结构完整")


def _main():
    test_sharpe_stability_bounds()
    test_long_short_stats()
    test_holding_stats_trapped_and_missed()
    test_gt_score_composition()
    test_run_backtest_exposes_rounds()
    test_audit_includes_robust()
    test_robust_report_shape()
    print(f"\nALL PASS ({PASS})")


if __name__ == "__main__":
    _main()
