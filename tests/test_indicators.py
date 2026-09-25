# -*- coding: utf-8 -*-
"""技术指标单测：用数学不变量与手工构造序列验证。可直接运行，也兼容 pytest。"""
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.quant.indicators import atr, boll, ema, kdj, latest_snapshot, macd, rsi, sma


def _df(closes, highs=None, lows=None, vols=None):
    idx = pd.date_range("2026-01-01", periods=len(closes), freq="B")
    return pd.DataFrame({
        "open": closes, "high": highs or [c * 1.01 for c in closes],
        "low": lows or [c * 0.99 for c in closes], "close": closes,
        "volume": vols or [1000] * len(closes), "amount": [0.0] * len(closes),
    }, index=idx)


def test_constant_series():
    s = pd.Series([10.0] * 40)
    assert sma(s, 5).iloc[-1] == 10.0
    assert abs(ema(s, 12).iloc[-1] - 10.0) < 1e-9
    dif, dea, hist = macd(s)
    assert abs(dif.iloc[-1]) < 1e-9 and abs(hist.iloc[-1]) < 1e-9
    assert rsi(s).iloc[-1] == 50.0  # 无波动 → 中性 50


def test_all_up_rsi_is_100():
    s = pd.Series(np.arange(1.0, 40.0))
    assert rsi(s).iloc[-1] == 100.0


def test_all_down_rsi_is_0():
    s = pd.Series(np.arange(40.0, 1.0, -1.0))
    out = rsi(s)
    assert out.iloc[-1] == 0.0


def test_boll_bands_order():
    s = pd.Series(np.sin(np.arange(60) / 5) * 10 + 100)
    mid, up, low = boll(s)
    assert low.iloc[-1] < mid.iloc[-1] < up.iloc[-1]
    # 中轨即 20 日均线
    assert abs(mid.iloc[-1] - sma(s, 20).iloc[-1]) < 1e-9


def test_kdj_range_and_j():
    df = _df(list(np.sin(np.arange(60) / 4) * 10 + 100))
    k, d, j = kdj(df["high"], df["low"], df["close"])
    assert 0 <= k.iloc[-1] <= 100 and 0 <= d.iloc[-1] <= 100
    assert abs(j.iloc[-1] - (3 * k.iloc[-1] - 2 * d.iloc[-1])) < 1e-9


def test_kdj_manual_known_values():
    # 手工构造：前 8 日 close 恒为 10（high=11,low=9），第 9 日收 11（最高11 最低9）
    n = 9
    closes = [10.0] * 8 + [11.0]
    highs = [11.0] * n
    lows = [9.0] * n
    df = _df(closes, highs=highs, lows=lows)
    k, d, j = kdj(df["high"], df["low"], df["close"])
    # 第 9 日 RSV=100；K = 2/3*50 + 1/3*100 = 66.6667；D = 2/3*50 + 1/3*K
    assert abs(k.iloc[-1] - 66.6666667) < 1e-4
    assert abs(d.iloc[-1] - (2 / 3 * 50 + 1 / 3 * 66.6666667)) < 1e-4


def test_atr_positive():
    df = _df(list(np.arange(1.0, 40.0)))
    a = atr(df["high"], df["low"], df["close"])
    assert a.iloc[-1] > 0


def test_snapshot_structure():
    df = _df(list(100 + np.sin(np.arange(120) / 6) * 5 + np.arange(120) * 0.05))
    snap = latest_snapshot(df)
    assert snap["bars"] == 120
    for key in ("ma", "macd", "kdj", "boll"):
        assert key in snap
    assert snap["rsi14"] is not None
    assert 0 <= snap["pos_in_60d_pct"] <= 100


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        fn()
        print(f"  PASS {fn.__name__}")
        passed += 1
    print(f"\n{passed}/{len(fns)} 个指标测试通过")


if __name__ == "__main__":
    _run_all()
