# -*- coding: utf-8 -*-
"""多标的组合回测单测：权重归一/再平衡/公共区间/交易日不齐/单标的一致性。可直接运行。"""
import math
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.portfolio.multi_backtest import (HoldingSpec, _normalize_weights,
                                            _rebalance_days, run_portfolio)
from core.quant.backtest import BacktestConfig, run_backtest


def _bars(n=300, drift=0.0, amp=8.0, base=100.0, skip=None, start="2023-01-02"):
    idx = pd.bdate_range(start, periods=n + len(skip or []))
    if skip:
        idx = idx.difference(pd.DatetimeIndex(skip))[:n]
    closes = []
    for i in range(len(idx)):
        closes.append(round(max(base + amp * math.sin(i / 6.0) + drift * (i - 150), 1.0), 3))
    return pd.DataFrame({
        "open": closes, "high": [c * 1.01 for c in closes],
        "low": [c * 0.99 for c in closes], "close": closes,
        "volume": [1e6] * len(idx), "amount": [0.0] * len(idx)}, index=idx)


def _map(**kw):
    return kw


# ---------- 权重 ----------
def test_normalize_weights():
    w = _normalize_weights(["A", "B"], [2.0, 1.0])
    assert abs(w.sum() - 1.0) < 1e-9 and abs(w[0] - 2 / 3) < 1e-9
    w2 = _normalize_weights(["A", "B", "C"], None)
    assert list(w2) == [1 / 3] * 3
    try:
        _normalize_weights([], None)
        assert False
    except ValueError:
        pass
    for bad in ([], [1.0], [1.0, -1.0], [0.0, 0.0]):
        try:
            _normalize_weights(["A", "B"], bad)
            assert False, f"应报错: {bad}"
        except ValueError:
            pass


# ---------- 再平衡日 ----------
def test_rebalance_days():
    idx = pd.DatetimeIndex(["2024-01-02", "2024-01-03", "2024-02-01", "2024-03-01",
                            "2024-04-01", "2024-06-03", "2025-01-02"])
    m = _rebalance_days(idx, "month")
    assert pd.Timestamp("2024-01-02") in m and pd.Timestamp("2024-02-01") in m
    q = _rebalance_days(idx, "quarter")
    dates = {d.strftime("%Y-%m-%d") for d in q}
    assert dates == {"2024-01-02", "2024-04-01", "2025-01-02"}
    assert _rebalance_days(idx, "none") == set()
    try:
        _rebalance_days(idx, "weekly")
        assert False
    except ValueError:
        pass


# ---------- 单标的一致性 ----------
def test_single_holding_matches_solo():
    df = _bars(300, drift=0.2)
    res = run_portfolio([HoldingSpec("SH600519")], bars_map=_map(SH600519=df))
    solo = run_backtest(df, "CN", "buy_hold", {},
                        BacktestConfig(ticker="SH600519", market="CN"))
    # 组合首日收益按0（与单回测差一个首日买入费），其余完全一致 → 误差<0.1pct
    assert abs(res.metrics["annual_return_pct"] - solo.metrics["annual_return_pct"]) < 0.1
    assert res.weight_track["SH600519"].iloc[-1] == 1.0


# ---------- 公共区间裁剪 ----------
def test_common_period_clipping():
    a = _bars(300, start="2023-01-02")
    b = _bars(300, start="2023-07-03")
    res = run_portfolio([HoldingSpec("SH600519"), HoldingSpec("SH510300")],
                        bars_map=_map(SH600519=a, SH510300=b))
    assert res.start >= b.index[0].strftime("%Y-%m-%d")
    # a 约剩 170 个交易日（b 晚起步半年）
    assert 150 <= len(res.equity) <= 175


def test_insufficient_overlap_raises():
    a = _bars(300, start="2023-01-02")
    b = _bars(100, start="2025-01-02")   # 与 a 完全不重叠
    try:
        run_portfolio([HoldingSpec("SH600519"), HoldingSpec("SH510300")],
                      bars_map=_map(SH600519=a, SH510300=b))
        assert False
    except ValueError:
        pass


# ---------- 交易日不齐（休市日收益0，组合不炸） ----------
def test_missing_market_days():
    a = _bars(120)
    # b 刻意缺 a 的若干交易日（模拟港股/A股节假日差异）
    b_full = _bars(120)
    skip_days = list(b_full.index[10:15]) + list(b_full.index[40:44])
    b = b_full.drop(pd.DatetimeIndex(skip_days))
    res = run_portfolio([HoldingSpec("SH600519"), HoldingSpec("0700.HK")],
                        bars_map=_map(SH600519=a, **{"0700.HK": b}))
    assert res.equity["strategy"].notna().all()
    assert (res.equity["strategy"] > 0).all()
    assert res.start and res.end and len(res.holdings) == 2
    assert res.metrics["bars"] == len(res.equity)


# ---------- 再平衡把漂移权重拉回 ----------
def test_rebalance_resets_weights():
    # a 强上涨漂移→权重应远离0.5；季末再平衡后当日收盘权重被拉回0.5
    a = _bars(300, drift=0.8, amp=1.0)
    b = _bars(300, drift=-0.1, amp=1.0)
    res_none = run_portfolio(
        [HoldingSpec("SH600519"), HoldingSpec("SH510300")],
        rebalance="none", bars_map=_map(SH600519=a, SH510300=b))
    drift_w = res_none.weight_track["SH600519"].iloc[-1]
    assert drift_w > 0.7   # 强者权重显著漂移
    res_q = run_portfolio(
        [HoldingSpec("SH600519"), HoldingSpec("SH510300")],
        rebalance="quarter", bars_map=_map(SH600519=a, SH510300=b))
    # 再平衡日收盘调仓、次日生效：取10月首个再平衡日的次一交易日，权重=0.5
    idx = pd.to_datetime(res_q.weight_track.index)
    oct_days = [i for i, d in enumerate(idx) if d.month == 10 and (i == 0 or idx[i - 1].month != 10)]
    if oct_days and oct_days[0] + 1 < len(idx):
        nxt = idx[oct_days[0] + 1].strftime("%Y-%m-%d")
        assert abs(res_q.weight_track.loc[nxt, "SH600519"] - 0.5) < 1e-9


# ---------- 统一策略组合 + 结构 ----------
def test_strategy_portfolio_structure():
    a = _bars(300, drift=0.15)
    b = _bars(300, drift=0.05)
    res = run_portfolio(
        [HoldingSpec("SH600519", 2.0), HoldingSpec("SH510300", 1.0)],
        strategy="ma_cross", params={"fast": 5, "slow": 20}, rebalance="month",
        bars_map=_map(SH600519=a, SH510300=b))
    assert abs(res.weights["SH600519"] - 2 / 3) < 1e-3
    assert abs(res.weights["SH510300"] - 1 / 3) < 1e-3
    assert res.strategy == "ma_cross" and res.params["fast"] == 5
    assert list(res.equity.columns) == ["strategy", "benchmark", "cash", "market_value"]
    for key in ("total_return_pct", "annual_return_pct", "max_drawdown_pct",
                "sharpe", "excess_return_pct", "benchmark_return_pct"):
        assert key in res.metrics
    for h in res.holdings:
        for key in ("ticker", "weight_pct", "annual_return_pct", "volatility_pct",
                    "max_drawdown_pct", "sharpe", "buy_hold_pct"):
            assert key in h


def test_unknown_ticker_raises():
    a = _bars(100)
    try:
        run_portfolio([HoldingSpec("SH600519"), HoldingSpec("NOTACOINXYZ")],
                      bars_map=_map(SH600519=a))
        assert False
    except ValueError:
        pass


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        fn()
        print(f"  PASS {fn.__name__}")
        passed += 1
    print(f"\n{passed}/{len(fns)} 个组合回测测试通过")


if __name__ == "__main__":
    _run_all()
