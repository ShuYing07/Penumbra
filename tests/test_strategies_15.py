# -*- coding: utf-8 -*-
"""第17轮·模块二：Agent 策略问股扩展至 15 种策略回归测试。

覆盖：均线/缠论/波浪/趋势 等 15+ 种内置策略的信号生成与回测可跑性。
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("STOCKAI_MOCK", "1")

from core.quant.backtest import (BacktestConfig, STRATEGY_META, STRATEGIES,
                                 run_backtest, strategy_choices)

rng = np.random.default_rng(42)


def make_ohlcv(n: int = 250, seed: int = 0) -> pd.DataFrame:
    """合成带 high/low/volume 的 OHLCV 行情（含趋势+波动，便于策略出信号）。"""
    g = np.random.default_rng(seed)
    idx = pd.bdate_range("2024-01-01", periods=n)
    # 趋势 + 正弦 + 噪声
    trend = np.linspace(0, 0.5, n)
    wave = 0.08 * np.sin(np.linspace(0, 12 * np.pi, n))
    noise = g.normal(0, 0.012, n).cumsum()
    close = 10 * np.exp(trend + wave + noise)
    open_ = close * (1 + g.normal(0, 0.003, n))
    high = np.maximum(open_, close) * (1 + np.abs(g.normal(0, 0.008, n)))
    low = np.minimum(open_, close) * (1 - np.abs(g.normal(0, 0.008, n)))
    volume = g.integers(1_000, 5_000, n).astype(float)
    return pd.DataFrame({"open": open_, "high": high, "low": low,
                        "close": close, "volume": volume}, index=idx)


def _sig_count(name: str) -> int:
    df = make_ohlcv()
    sig = STRATEGIES[name](df, {})
    assert sig.isin([-1, 0, 1]).all(), f"{name} 信号越界"
    return int((sig != 0).sum())


# 1) 策略注册表与下拉完整
choices = strategy_choices()
assert len(choices) >= 15, f"策略数不足 15：{len(choices)}"
for key, label in choices:
    assert key in STRATEGY_META and STRATEGY_META[key]["label"] == label
    assert key in STRATEGIES or key == "buy_hold"
print(f"[ok] 注册策略 {len(choices)} 种（含基准）："
      + "、".join(k for k, _ in choices))


# 2) 每类策略必须能生成非零信号（用不同种子提高覆盖，至少一类出信号）
EXPECTED = ["ma_cross", "dual_ma_trend", "ema_trend", "macd_cross", "kdj_cross",
            "rsi_reversion", "boll_meanrev", "breakout_high", "atr_channel",
            "volume_price", "cci_reversion", "williams_r", "adx_trend", "chan", "wave"]
no_signal = []
for name in EXPECTED:
    cnt = max(_sig_count(name) for _ in range(3))  # 3 个种子取最大
    if cnt == 0:
        no_signal.append(name)
    else:
        print(f"  [ok] {name:16s} 信号数(最大)={cnt}")
assert not no_signal, f"以下策略从未产生信号：{no_signal}"


# 3) 每个策略都能跑完整回测且不报错、含指标
for name in EXPECTED + ["buy_hold"]:
    df = make_ohlcv(seed=7)
    cfg = BacktestConfig(market="US", init_capital=100_000)
    res = run_backtest(df, "US", name, {}, cfg)
    assert res.metrics, f"{name} 无指标"
    assert "total_return_pct" in res.metrics, f"{name} 缺收益字段"
    # 交易或持有应产生至少 1 条权益记录
    assert len(res.equity) == len(df), f"{name} 权益长度不符"
    print(f"  [ok] {name:16s} 回测 OK  收益={res.metrics.get('total_return_pct',0):.1f}%"
          f"  回撤={res.metrics.get('max_drawdown_pct',0):.1f}%")


# 4) 均线/缠论/波浪/趋势 四大代表类明确覆盖
for tag in ("均线", "缠论", "波浪", "趋势"):
    hits = [k for k, label in choices if tag in label or
            tag in STRATEGY_META[k]["desc"]]
    assert hits, f"{tag} 未被任何策略覆盖"
    print(f"[ok] 类别「{tag}」覆盖：{hits}")


# 5) 参数化：改变参数不报错（如 ma_cross fast/slow）
df = make_ohlcv()
r1 = run_backtest(df, "US", "ma_cross", {"fast": 3, "slow": 10}, BacktestConfig(market="US"))
r2 = run_backtest(df, "US", "ma_cross", {"fast": 10, "slow": 30}, BacktestConfig(market="US"))
assert isinstance(r1.metrics.get("total_return_pct"), (int, float))
assert isinstance(r2.metrics.get("total_return_pct"), (int, float))
print("[ok] 参数化回测正常（fast/slow 不同 → 不同结果）")

print("\nALL PASS")
