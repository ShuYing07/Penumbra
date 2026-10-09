# -*- coding: utf-8 -*-
"""core/quant/assumption_audit.py 九维回测假设审计单测。

覆盖：9 个维度是否都被覆盖、零成本/零滑点告警、停牌 bar、流动性超载、
幸存者偏差、分红除权、时间对齐委派、报告格式、零误报（健康数据全 OK）。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from core.quant import assumption_audit as aa
from core.quant.backtest import BacktestConfig, FeeModel


def _bars(n: int = 120, vol: float = 1e7, price: float = 10.0,
          zero_vol_from: int | None = None) -> pd.DataFrame:
    # 交易日序列（自然日会触发 chronoaudit 的「周末 bar」告警，用 B 口径保持干净）
    idx = pd.date_range("2024-01-02", periods=n, freq="B")
    v = [float(vol)] * n
    if zero_vol_from is not None:
        for i in range(zero_vol_from, n):
            v[i] = 0.0
    return pd.DataFrame({
        "open": [price] * n,
        "high": [price * 1.01] * n,
        "low": [price * 0.99] * n,
        "close": [price] * n,
        "volume": v,
    }, index=idx)


def _ids(rep):
    return [f["id"] for f in rep["findings"]]


def _sev(rep, dim):
    for f in rep["findings"]:
        if f["id"] == dim:
            return f["severity"]
    return None


# --------------------------------------------------------------------------
# 1. 维度覆盖
# --------------------------------------------------------------------------
def test_dimensions_declared():
    assert len(aa.DIMENSIONS) == 9
    keys = {d["id"] for d in aa.DIMENSIONS}
    assert keys == {"data_availability", "fill", "liquidity", "cost", "slippage",
                    "survivorship", "time_alignment", "market_impact", "dividend"}
    for d in aa.DIMENSIONS:
        assert d["name"] and d["question"]


def test_healthy_backtest_covers_all_nine():
    """健康回测：9 维全部覆盖，且无 FATAL。"""
    df = _bars()
    cfg = BacktestConfig(ticker="TEST", market="CN",
                         fee=FeeModel(commission_rate=2.5e-4,
                                      stamp_tax_sell=5e-4,
                                      slippage_bps=5.0))
    rep = aa.audit_assumptions(df, "CN", "ma_cross", {}, cfg,
                               universe=["TEST"], capital=1e5, position_pct=10)
    assert rep["covered"] == 9, sorted(set(_ids(rep)))
    assert rep["passed"] is True
    assert rep["counts"]["FATAL"] == 0


# --------------------------------------------------------------------------
# 2. 数据可用性
# --------------------------------------------------------------------------
def test_empty_df_is_fatal():
    rep = aa.audit_assumptions(None)
    assert rep["passed"] is False
    assert _sev(rep, "data_availability") == "FATAL"


def test_nan_close_is_fatal():
    df = _bars(60)
    df.loc[df.index[:5], "close"] = float("nan")
    rep = aa.audit_assumptions(df, universe=["X"])
    assert _sev(rep, "data_availability") == "FATAL"


def test_suspended_bars_flagged():
    df = _bars(100, zero_vol_from=70)   # 30% 零成交 → FATAL
    rep = aa.audit_assumptions(df, universe=["X"])
    assert _sev(rep, "data_availability") == "FATAL"
    df2 = _bars(200, zero_vol_from=197)  # 1.5% → WARN
    rep2 = aa.audit_assumptions(df2, universe=["X"])
    assert _sev(rep2, "data_availability") == "WARN"


# --------------------------------------------------------------------------
# 3. 成交假设
# --------------------------------------------------------------------------
def test_fill_assumption_always_declared():
    rep = aa.audit_assumptions(_bars(), universe=["X"])
    assert _sev(rep, "fill") == "INFO"
    assert "shift" in [f["fix"] for f in rep["findings"] if f["id"] == "fill"][0]


# --------------------------------------------------------------------------
# 4. 流动性
# --------------------------------------------------------------------------
def test_liquidity_oversize_is_fatal():
    df = _bars(vol=1e5, price=10.0)          # 日均成交 1e6
    rep = aa.audit_assumptions(df, universe=["X"], capital=1e8, position_pct=100)
    assert _sev(rep, "liquidity") == "FATAL"
    assert _sev(rep, "market_impact") == "WARN"


def test_liquidity_ok_when_small():
    df = _bars(vol=1e7, price=10.0)          # 日均成交 1e8
    rep = aa.audit_assumptions(df, universe=["X"], capital=1e5, position_pct=10)
    assert _sev(rep, "liquidity") == "OK"
    assert _sev(rep, "market_impact") == "OK"


def test_liquidity_warn_band():
    df = _bars(vol=1e6, price=10.0)          # 日均成交 1e7
    rep = aa.audit_assumptions(df, universe=["X"], capital=1e6, position_pct=100)
    assert _sev(rep, "liquidity") == "WARN"


# --------------------------------------------------------------------------
# 5. 成本 / 滑点
# --------------------------------------------------------------------------
def test_zero_cost_warned():
    cfg = BacktestConfig(fee=FeeModel(commission_rate=0.0, stamp_tax_sell=0.0,
                                      slippage_bps=0.0))
    rep = aa.audit_assumptions(_bars(), "CN", "ma_cross", {}, cfg, universe=["X"])
    assert _sev(rep, "cost") == "WARN"
    assert _sev(rep, "slippage") == "WARN"


def test_none_config_warned():
    rep = aa.audit_assumptions(_bars(), universe=["X"])
    assert _sev(rep, "cost") == "WARN"


def test_cost_modelled_ok():
    cfg = BacktestConfig(fee=FeeModel(commission_rate=2.5e-4, stamp_tax_sell=5e-4,
                                      slippage_bps=5.0))
    rep = aa.audit_assumptions(_bars(), "CN", "ma_cross", {}, cfg, universe=["X"])
    assert _sev(rep, "cost") == "OK"
    assert _sev(rep, "slippage") == "OK"


# --------------------------------------------------------------------------
# 6. 幸存者偏差
# --------------------------------------------------------------------------
def test_universe_none_is_info():
    rep = aa.audit_assumptions(_bars())
    assert _sev(rep, "survivorship") == "INFO"


def test_single_universe_ok():
    rep = aa.audit_assumptions(_bars(), universe=["600519"])
    assert _sev(rep, "survivorship") == "OK"


def test_multi_universe_warn():
    rep = aa.audit_assumptions(_bars(), universe=[f"{i:06d}" for i in range(30)])
    assert _sev(rep, "survivorship") == "WARN"


# --------------------------------------------------------------------------
# 7. 时间对齐（委派 chronoaudit）
# --------------------------------------------------------------------------
def test_time_alignment_ok_on_clean_series():
    rep = aa.audit_assumptions(_bars(), "CN", universe=["X"])
    assert _sev(rep, "time_alignment") == "OK"


def test_time_alignment_fatal_on_duplicate_timestamps():
    df = _bars(30)
    df = pd.concat([df, df.iloc[:3]])       # 重复时间戳
    rep = aa.audit_assumptions(df, "CN", universe=["X"])
    assert _sev(rep, "time_alignment") == "FATAL"
    assert rep["passed"] is False


# --------------------------------------------------------------------------
# 8. 分红除权
# --------------------------------------------------------------------------
def test_no_adjust_price_warned():
    rep = aa.audit_assumptions(_bars(), universe=["X"])
    assert _sev(rep, "dividend") == "WARN"


def test_adjusted_price_ok():
    df = _bars()
    df["hfq_close"] = df["close"]
    rep = aa.audit_assumptions(df, universe=["X"])
    assert _sev(rep, "dividend") == "OK"


# --------------------------------------------------------------------------
# 9. 排序 / 计数 / 报告
# --------------------------------------------------------------------------
def test_findings_sorted_by_severity():
    rep = aa.audit_assumptions(None)
    order = [f["severity"] for f in rep["findings"]]
    rank = {"FATAL": 0, "WARN": 1, "INFO": 2, "OK": 3}
    assert order == sorted(order, key=lambda s: rank[s])


def test_counts_sum_to_findings():
    rep = aa.audit_assumptions(_bars(), universe=["A", "B"])
    assert sum(rep["counts"].values()) == len(rep["findings"])
    assert "9 维" in rep["summary"]


def test_format_report_hides_ok_and_shows_fix():
    rep = aa.audit_assumptions(None)
    txt = aa.format_report(rep)
    assert "修复" in txt and "证据" in txt
    assert "[OK]" not in txt
    assert "不可用于任何决策" in txt


def test_format_report_clean_output():
    cfg = BacktestConfig(fee=FeeModel(commission_rate=2.5e-4, stamp_tax_sell=5e-4,
                                      slippage_bps=5.0))
    df = _bars()
    df["hfq_close"] = df["close"]
    rep = aa.audit_assumptions(df, "CN", "ma_cross", {}, cfg,
                               universe=["X"], capital=1e4, position_pct=10)
    txt = aa.format_report(rep)
    assert "⛔" not in txt


def test_no_false_positive_on_illiquid_but_tiny_order():
    """零误报：小盘股 + 极小资金，不应报流动性/冲击问题。"""
    df = _bars(vol=1e4, price=3.0)          # 日均成交 3e4（极小盘）
    rep = aa.audit_assumptions(df, universe=["X"], capital=1e3, position_pct=10)
    assert _sev(rep, "liquidity") == "OK"
    assert _sev(rep, "market_impact") == "OK"


if __name__ == "__main__":
    for name, fn in sorted(list(globals().items())):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok  {name}")
    print("ALL OK")
