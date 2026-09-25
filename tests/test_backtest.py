# -*- coding: utf-8 -*-
"""回测引擎确定性单测：防前视、费用、整手、指标手算。可直接运行，兼容 pytest。"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.quant.backtest import (  # noqa: E402
    BacktestConfig, FeeModel, compute_metrics, run_backtest,
    _lot_shares, _sig_rsi,
)

ZERO_FEE = FeeModel(commission_rate=0.0, min_commission=0.0, stamp_tax_sell=0.0,
                    transfer_fee=0.0, slippage_bps=0.0)


def approx(a, b, abs_=1e-6):
    return abs(a - b) <= abs_


def expect_raises(exc, fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except exc:
        return
    raise AssertionError(f"期望抛出 {exc.__name__}，但未抛出")


def make_df(closes, opens=None):
    """由收盘序列构造 OHLCV DataFrame（open 默认=前收，首日=收盘）。"""
    closes = [float(x) for x in closes]
    if opens is None:
        opens = [closes[0]] + closes[:-1]
    idx = pd.bdate_range("2024-01-01", periods=len(closes))
    return pd.DataFrame({
        "open": opens, "high": [max(o, c) for o, c in zip(opens, closes)],
        "low": [min(o, c) for o, c in zip(opens, closes)],
        "close": closes, "volume": [1_000_000] * len(closes),
        "amount": [0.0] * len(closes),
    }, index=idx)


# --------------------------------------------------------------------------
# 费率 / 交易单位
# --------------------------------------------------------------------------

def test_fee_cn_buy_min_commission():
    fee = FeeModel(commission_rate=0.00025, min_commission=5.0,
                   stamp_tax_sell=0.0005, transfer_fee=0.00001)
    # 金额 10000：佣金比例额=2.5 < 最低 5；过户费 0.1
    assert approx(fee.buy_fee(10_000), 5.1, 1e-6)


def test_fee_cn_sell_includes_stamp():
    fee = FeeModel(commission_rate=0.00025, min_commission=5.0,
                   stamp_tax_sell=0.0005, transfer_fee=0.00001)
    # 卖出 10000：佣金 5 + 印花税 5 + 过户费 0.1
    assert approx(fee.sell_fee(10_000), 10.1, 1e-6)


def test_lot_shares_cn():
    assert _lot_shares("CN", 1_500, 10) == 100           # 1 手
    assert _lot_shares("CN", 15_000, 10) == 1500         # 15 手
    assert _lot_shares("CN", 9_999, 100) == 0            # 不足 1 手
    assert approx(_lot_shares("US", 10_000, 123.4567), 81.0, 0.01)
    assert approx(_lot_shares("CRYPTO", 10_000, 50_000), 0.2, 1e-6)


# --------------------------------------------------------------------------
# 防前视：信号日 t → 成交价 = t+1 open
# --------------------------------------------------------------------------

def test_no_lookahead_fill_at_next_open():
    # 2 日平开后，第 5 日收盘拉到 110，SMA1 上穿 SMA3（金叉）；次日开盘 105 成交
    closes = [100, 100, 100, 100, 100, 110, 110, 110, 100, 100,
              100, 100, 100, 100, 100, 100, 100, 100, 100, 100,
              100, 100, 100, 100, 100, 100, 100, 100, 100, 100]
    opens = [100, 100, 100, 100, 100, 100, 105, 110, 110, 100] + [100] * 20
    df = make_df(closes, opens)
    cfg = BacktestConfig(ticker="TEST", market="CN", init_capital=1_000_000,
                         position_pct=100, fee=ZERO_FEE)
    res = run_backtest(df, "CN", "ma_cross", {"fast": 1, "slow": 3}, cfg)
    buys = res.trades[res.trades["side"] == "买入"]
    assert len(buys) >= 1
    first = buys.iloc[0]
    assert first["fill_date"] == "2024-01-09"   # 信号日 01-08（i=5）次日
    assert approx(float(first["price"]), 105.0)  # 精确等于次日开盘（零滑点）


def test_last_bar_signal_not_filled():
    # 末根 K 线才金叉，无次日可成交 → 不应有买入
    closes = [100] * 29 + [110]
    df = make_df(closes)
    cfg = BacktestConfig(ticker="TEST", market="CN", fee=ZERO_FEE)
    res = run_backtest(df, "CN", "ma_cross", {"fast": 1, "slow": 3}, cfg)
    assert len(res.trades) == 0


# --------------------------------------------------------------------------
# RSI 策略信号与交易方向
# --------------------------------------------------------------------------

def test_rsi_signals_on_v_shape():
    # 2 平 + 20 连跌（RSI→0，出买点）+ 20 连涨（RSI→100，出卖点）
    closes = [100, 100]
    p = 100.0
    for _ in range(20):
        p *= 0.98
        closes.append(p)
    for _ in range(20):
        p *= 1.02
        closes.append(p)
    df = make_df(closes)
    sig = _sig_rsi(df, {"rsi_period": 14, "buy_thr": 30, "sell_thr": 70})
    assert (sig == 1).any() and (sig == -1).any()

    cfg = BacktestConfig(ticker="TEST", market="US", init_capital=100_000, fee=ZERO_FEE)
    res = run_backtest(df, "US", "rsi_reversion", {}, cfg)
    sides = res.trades["side"].tolist()
    assert sides[0] == "买入" and sides[-1] == "卖出"
    # 买卖严格交替
    for a, b in zip(sides, sides[1:]):
        assert a != b
    assert res.metrics["closed_rounds"] >= 1
    # 低买高卖回合应盈利（V 形终点高于下跌途中买入价区）
    assert res.metrics["win_rate_pct"] >= 50.0


def test_warmup_insufficient_data():
    df = make_df([100 - i for i in range(29)])
    cfg = BacktestConfig(ticker="TEST", market="CN", fee=ZERO_FEE)
    expect_raises(ValueError, run_backtest, df, "CN", "rsi_reversion", {}, cfg)


# --------------------------------------------------------------------------
# 买入持有基准
# --------------------------------------------------------------------------

def test_buy_hold_first_open():
    closes = [100, 101, 102, 103] + [105] * 30
    df = make_df(closes)
    cfg = BacktestConfig(ticker="TEST", market="US", init_capital=100_000,
                         position_pct=100, fee=ZERO_FEE)
    res = run_backtest(df, "US", "buy_hold", {}, cfg)
    assert len(res.trades) == 1
    assert approx(float(res.trades.iloc[0]["price"]), 100.0)  # 首日开盘
    # 末日收盘 105 → 总收益约 +5%
    assert approx(res.metrics["total_return_pct"], 5.0, 0.1)


# --------------------------------------------------------------------------
# 绩效指标手算
# --------------------------------------------------------------------------

def _equity(values):
    idx = pd.bdate_range("2024-01-01", periods=len(values)).strftime("%Y-%m-%d")
    return pd.DataFrame({"strategy": values, "benchmark": values,
                         "cash": values, "market_value": [0.0] * len(values)}, index=idx)


def test_metrics_flat():
    eq = _equity([1_000_000.0] * 40)
    m = compute_metrics(eq, pd.DataFrame(), [], BacktestConfig())
    assert m["total_return_pct"] == 0.0
    assert m["max_drawdown_pct"] == 0.0
    assert m["sharpe"] == 0.0
    assert m["win_rate_pct"] == 0.0


def test_metrics_monotonic_up_and_drawdown():
    # 252 日每日 +1000，最大回撤=0；末期权益 1_251_000
    vals = [1_000_000.0 + 1000 * i for i in range(252)]
    m = compute_metrics(_equity(vals), pd.DataFrame(), [], BacktestConfig())
    assert approx(m["total_return_pct"], 25.1, 0.01)
    assert m["max_drawdown_pct"] == 0.0
    assert approx(m["annual_return_pct"], 25.1, 0.2)

    # 手算回撤：100 万→120 万→90 万→110 万，最大回撤 -25%
    m2 = compute_metrics(_equity([1_000_000, 1_200_000, 900_000, 1_100_000] * 10),
                         pd.DataFrame(), [], BacktestConfig())
    assert approx(m2["max_drawdown_pct"], -25.0, 0.01)


def test_metrics_win_rate_and_pl_ratio():
    eq = _equity([1_000_000.0] * 40)
    rounds = [{"pnl": 3000.0, "hold_days": 5}, {"pnl": -1000.0, "hold_days": 3},
              {"pnl": 1000.0, "hold_days": 4}]
    m = compute_metrics(eq, pd.DataFrame(), rounds, BacktestConfig())
    assert approx(m["win_rate_pct"], 66.67, 0.01)
    # 平均盈 2000 / 平均亏 1000 = 2.0
    assert approx(m["profit_loss_ratio"], 2.0, 0.01)
    assert approx(m["avg_hold_days"], 4.0, 0.01)


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        fn()
        print(f"  PASS {fn.__name__}")
        passed += 1
    print(f"\n{passed}/{len(fns)} 个回测测试通过")


if __name__ == "__main__":
    _run_all()
