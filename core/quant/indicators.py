# -*- coding: utf-8 -*-
"""技术指标纯函数（通达信/同花顺口径）：MA/EMA/MACD/RSI/KDJ/BOLL/ATR 及事实快照。

约定：
- 输入为 pandas.Series（按日期升序，索引为日期）或 DataFrame(open/high/low/close/volume)；
- 全部为纯函数，无网络、无副作用，便于单测；
- 不确定值用 None（快照 JSON 友好），Series 中用 NaN。
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).mean()


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    """返回 (DIF, DEA, MACD柱)。国内惯例柱 = 2*(DIF-DEA)。"""
    dif = ema(close, fast) - ema(close, slow)
    dea = dif.ewm(span=signal, adjust=False).mean()
    hist = (dif - dea) * 2
    return dif, dea, hist


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    """Wilder RSI。"""
    delta = close.diff()
    up = delta.clip(lower=0.0)
    down = -delta.clip(upper=0.0)
    roll_up = up.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()
    roll_down = down.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()
    rs = roll_up / roll_down.replace(0.0, np.nan)
    out = 100.0 - 100.0 / (1.0 + rs)
    # 连续 n 日全涨 → 100；全跌 → 0；涨跌皆无（常量）→ 中性 50
    out = out.where(roll_down != 0, 100.0)
    out = out.where(~((roll_up == 0) & (roll_down == 0)), 50.0)
    return out


def kdj(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 9, m1: int = 3, m2: int = 3):
    """返回 (K, D, J)。RSV 后按国内 SMA(X,M,1) 递推，初值 50。"""
    low_n = low.rolling(n, min_periods=n).min()
    high_n = high.rolling(n, min_periods=n).max()
    rsv = (close - low_n) / (high_n - low_n) * 100.0
    k = np.full(len(close), np.nan)
    d = np.full(len(close), np.nan)
    pk = pd_ = 50.0
    for i, r in enumerate(rsv.to_numpy()):
        if not np.isnan(r):
            pk = (m1 - 1) / m1 * pk + r / m1
            pd_ = (m2 - 1) / m2 * pd_ + pk / m2
        if i >= n - 1:
            k[i] = pk
            d[i] = pd_
    k_s, d_s = pd.Series(k, index=close.index), pd.Series(d, index=close.index)
    j_s = 3 * k_s - 2 * d_s
    return k_s, d_s, j_s


def boll(close: pd.Series, n: int = 20, k: float = 2.0):
    """返回 (中轨, 上轨, 下轨)。通达信 STD 为总体标准差 ddof=0。"""
    mid = sma(close, n)
    std = close.rolling(n, min_periods=n).std(ddof=0)
    return mid, mid + k * std, mid - k * std


def atr(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 14) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()


def _f(x) -> float | None:
    try:
        if x is None or (isinstance(x, float) and (np.isnan(x) or np.isinf(x))):
            return None
        return round(float(x), 4)
    except (TypeError, ValueError):
        return None


def _pct(a: float | None, b: float | None) -> float | None:
    if a is None or b is None or b == 0:
        return None
    return round((a / b - 1.0) * 100.0, 2)


def latest_snapshot(df: pd.DataFrame, bars_required: int = 60) -> dict[str, Any]:
    """把行情 DataFrame 压缩成喂给 LLM 的"技术面事实清单"（数字全部程序算好）。"""
    if df is None or len(df) < 2:
        return {"error": "行情数据不足"}
    df = df.sort_index()
    close, high, low, vol = df["close"], df["high"], df["low"], df["volume"]
    last = close.iloc[-1]
    prev = close.iloc[-2]

    ma = {f"MA{n}": _f(sma(close, n).iloc[-1]) for n in (5, 10, 20, 60)}
    dif, dea, hist = macd(close)
    k, d, j = kdj(high, low, close)
    _, boll_up, boll_low = boll(close)
    atr14 = atr(high, low, close)

    lookback = {n: (df.index[-1].strftime("%Y-%m-%d"),
                    _pct(float(close.iloc[-1]), float(close.iloc[-1 - n])))
                for n in (1, 5, 20, 60) if len(close) > n}

    vol5 = vol.tail(5).mean()
    vol20 = vol.tail(20).mean()
    hi60, lo60 = float(high.tail(60).max()), float(low.tail(60).min())

    # 金叉/死叉（当日 DIF 与 DEA 相对位置较前一日变化）
    cross = None
    if len(close) >= 2 and not np.isnan(dif.iloc[-1]) and not np.isnan(dif.iloc[-2]):
        if dif.iloc[-1] > dea.iloc[-1] and dif.iloc[-2] <= dea.iloc[-2]:
            cross = "MACD金叉"
        elif dif.iloc[-1] < dea.iloc[-1] and dif.iloc[-2] >= dea.iloc[-2]:
            cross = "MACD死叉"

    return {
        "asof": df.index[-1].strftime("%Y-%m-%d"),
        "bars": int(len(df)),
        "close": _f(last),
        "prev_close": _f(prev),
        "chg_pct_1d": _pct(float(last), float(prev)),
        "chg_pct_periods": {k2: v for k2, (_, v) in lookback.items()},
        "ma": ma,
        "macd": {"DIF": _f(dif.iloc[-1]), "DEA": _f(dea.iloc[-1]), "HIST": _f(hist.iloc[-1]), "signal": cross},
        "rsi14": _f(rsi(close).iloc[-1]),
        "kdj": {"K": _f(k.iloc[-1]), "D": _f(d.iloc[-1]), "J": _f(j.iloc[-1])},
        "boll": {"up": _f(boll_up.iloc[-1]), "mid": ma["MA20"], "low": _f(boll_low.iloc[-1])},
        "atr14": _f(atr14.iloc[-1]),
        "atr14_pct": (lambda a: round(float(a) / float(last) * 100, 2) if a else None)(
            _f(atr14.iloc[-1])),
        "vol_ratio_5_20": _f(vol5 / vol20) if vol20 else None,
        "high_60d": _f(hi60),
        "low_60d": _f(lo60),
        "pos_in_60d_pct": _pct(float(last), lo60) and round((float(last) - lo60) / (hi60 - lo60) * 100, 1)
        if hi60 > lo60 else None,
    }
