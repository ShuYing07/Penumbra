# -*- coding: utf-8 -*-
"""参数寻优单测：网格展开、批量回测排名、平原评估、walk-forward。可直接运行。"""
import math
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.optimize import grid as G
from core.quant.backtest import BacktestConfig, run_backtest


def _bars(n=300, trend=True, start="2023-01-01"):
    """正弦波动 + 后段上涨趋势：趋势策略多组参数都能盈利（平原），也有信号可交易。"""
    idx = pd.bdate_range(start, periods=n)
    closes = []
    for i in range(n):
        wave = 100 + 8 * math.sin(i / 6.0)
        drift = (i - n * 0.5) * 0.15 if trend else 0.0
        closes.append(round(max(wave + drift, 1.0), 3))
    df = pd.DataFrame({
        "open": closes,
        "high": [c * 1.01 for c in closes],
        "low": [c * 0.99 for c in closes],
        "close": closes,
        "volume": [1e6] * n, "amount": [0.0] * n,
    }, index=idx)
    return df


# ---------- 网格展开 ----------
def test_expand_grid_cartesian():
    spec = {"a": [1, 2], "b": [10, 20, 30]}
    combos = G.expand_grid(spec)
    assert len(combos) == 6
    assert {"a": 1, "b": 10} in combos and {"a": 2, "b": 30} in combos


def test_expand_grid_empty_and_cap():
    try:
        G.expand_grid({})
        assert False
    except ValueError:
        pass
    big = {"p": list(range(G.MAX_COMBOS + 1))}
    try:
        G.expand_grid(big)
        assert False
    except ValueError:
        pass


# ---------- 批量回测 ----------
def test_run_grid_ranking_and_structure():
    df = _bars()
    spec = {"fast": [3, 5, 10], "slow": [20, 30]}
    res = G.run_grid(df, "CN", "ma_cross", spec,
                     BacktestConfig(ticker="SH600519", market="CN"),
                     objective="sharpe")
    assert len(res) == 6
    assert all(set(r) == {"params", "objective_name", "objective", "traded", "metrics"}
               for r in res)
    traded = [r for r in res if r["traded"]]
    assert len(traded) >= 2                       # 趋势数据均线策略应有交易
    objs = [r["objective"] for r in traded]
    assert objs == sorted(objs, reverse=True)     # 降序
    assert res[0]["objective_name"] == "sharpe"
    # 未交易组合排末尾
    assert all(r["traded"] for r in res[:len(traded)])


def test_run_grid_rejects_buy_hold():
    df = _bars()
    try:
        G.run_grid(df, "CN", "buy_hold", {})
        assert False
    except ValueError:
        pass


def test_objectives_present():
    df = _bars()
    spec = {"fast": [5], "slow": [20]}
    for obj in ("sharpe", "return", "calmar"):
        res = G.run_grid(df, "CN", "ma_cross", spec, objective=obj)
        assert res[0]["objective_name"] == obj
    try:
        G.run_grid(df, "CN", "ma_cross", spec, objective="xxx")
        assert False
    except ValueError:
        pass


# ---------- 平原评估（纯函数） ----------
def test_assess_plateau_flat_vs_spike():
    spec = {"p": [1, 2, 3]}
    # 平原：三个组合目标值接近
    flat = [
        {"params": {"p": 2}, "objective": 1.00, "traded": True, "metrics": {}},
        {"params": {"p": 1}, "objective": 0.95, "traded": True, "metrics": {}},
        {"params": {"p": 3}, "objective": 0.97, "traded": True, "metrics": {}},
    ]
    pa = G.assess_plateau(flat, spec)
    assert pa["robust"] >= 0.7 and "平原" in pa["rating"]

    # 尖峰：最优 1.0，邻居 0.0（极差 1，平均距离 1 → robust=0）
    spike = [
        {"params": {"p": 2}, "objective": 1.0, "traded": True, "metrics": {}},
        {"params": {"p": 1}, "objective": 0.0, "traded": True, "metrics": {}},
        {"params": {"p": 3}, "objective": 0.0, "traded": True, "metrics": {}},
    ]
    pb = G.assess_plateau(spike, spec)
    assert pb["robust"] <= 0.4 and "尖峰" in pb["rating"]
    # 邻居识别正确
    assert {n["params"]["p"] for n in pb["neighbors"]} == {1, 3}


def test_assess_plateau_no_neighbors():
    spec = {"p": [2]}
    rows = [{"params": {"p": 2}, "objective": 1.0, "traded": True, "metrics": {}}]
    pa = G.assess_plateau(rows, spec)
    assert pa["robust"] is None


# ---------- walk-forward ----------
def test_walk_forward_structure():
    df = _bars(360)
    spec = {"fast": [3, 5, 10], "slow": [20, 30]}
    wf = G.walk_forward(df, "CN", "ma_cross", spec,
                        BacktestConfig(ticker="SH600519", market="CN"),
                        split=0.6, objective="sharpe")
    assert wf["is_bars"] + wf["oos_bars"] == len(df)
    assert set(wf["is_best_params"]) == {"fast", "slow"}
    assert 0.0 <= wf["oos_percentile"] <= 1.0
    assert "is_metrics" in wf and "oos_metrics_of_is_best" in wf
    assert "rating" in wf and wf["oos_ex_post_best"]["params"]


def test_walk_forward_bad_split():
    df = _bars()
    spec = {"fast": [5], "slow": [20]}
    try:
        G.walk_forward(df, "CN", "ma_cross", spec, split=0.95)
        assert False
    except ValueError:
        pass


# ---------- 总入口 ----------
def test_optimize_end_to_end():
    df = _bars()
    spec = {"fast": [3, 5], "slow": [20, 30]}
    seen = []
    out = G.optimize(df, "CN", "ma_cross", spec,
                     BacktestConfig(ticker="SH600519", market="CN"),
                     progress_cb=lambda stage, i, t: seen.append(stage))
    assert out["n_combos"] == 4 and out["best"]["traded"]
    assert "rating" in out["plateau"] and "rating" in out["walk_forward"]
    assert set(seen) >= {"grid", "plateau", "walkforward"}


def test_default_grids_valid():
    # 三个策略的默认网格都能跑通真实引擎（数据足够长）
    df = _bars(400)
    for strat in ("rsi_reversion", "ma_cross", "macd_cross"):
        out = G.optimize(df, "CN", strat)
        assert out["n_combos"] == len(G.expand_grid(G.DEFAULT_GRIDS[strat]))


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        fn()
        print(f"  PASS {fn.__name__}")
        passed += 1
    print(f"\n{passed}/{len(fns)} 个参数寻优测试通过")


if __name__ == "__main__":
    _run_all()
