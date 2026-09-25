# -*- coding: utf-8 -*-
"""威科夫量价结构识别：Spring/Upthrust/Sign of Strength。

纯规则引擎，不依赖ML模型。参考WyckoffAgent的设计。
"""
from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import pandas as pd

log = logging.getLogger("stockai.wyckoff")


def identify_spring(df: pd.DataFrame, lookback: int = 20,
                    vol_mult: float = 1.5) -> Optional[dict]:
    """识别Spring（假跌破支撑后快速收回）。

    条件：
    1. 近lookback日内有明显支撑位
    2. 当日最低价跌破支撑2%以上
    3. 当日收盘价收回支撑上方
    4. 当日成交量放大
    """
    if len(df) < lookback + 5:
        return None

    recent = df.tail(lookback)
    support = recent["low"].min()
    today = df.iloc[-1]
    avg_vol = recent["volume"].mean()

    # 跌破支撑2%以上但收盘收回
    broke_below = today["low"] < support * 0.98
    closed_above = today["close"] > support
    vol_spike = today["volume"] > avg_vol * vol_mult

    if broke_below and closed_above and vol_spike:
        return {
            "pattern": "Spring（弹簧效应）",
            "confidence": "中",
            "description": f"假跌破支撑{support:.2f}后快速收回，放量确认",
            "date": str(df.index[-1])[:10],
        }
    return None


def identify_upthrust(df: pd.DataFrame, lookback: int = 20,
                      vol_mult: float = 1.5) -> Optional[dict]:
    """识别Upthrust（假突破阻力后快速回落）。

    条件：
    1. 近lookback日内有明显阻力位
    2. 当日最高价突破阻力2%以上
    3. 当日收盘价回落阻力下方
    4. 当日成交量放大
    """
    if len(df) < lookback + 5:
        return None

    recent = df.tail(lookback)
    resistance = recent["high"].max()
    today = df.iloc[-1]
    avg_vol = recent["volume"].mean()

    broke_above = today["high"] > resistance * 1.02
    closed_below = today["close"] < resistance
    vol_spike = today["volume"] > avg_vol * vol_mult

    if broke_above and closed_below and vol_spike:
        return {
            "pattern": "Upthrust（上冲回落）",
            "confidence": "中",
            "description": f"假突破阻力{resistance:.2f}后快速回落，放量确认",
            "date": str(df.index[-1])[:10],
        }
    return None


def identify_sign_of_strength(df: pd.DataFrame, lookback: int = 20,
                               vol_mult: float = 2.0) -> Optional[dict]:
    """识别Sign of Strength（SOS：放量突破上涨）。

    条件：
    1. 当日涨幅>2%
    2. 成交量>均量2倍
    3. 收盘价接近当日最高价
    """
    if len(df) < lookback + 5:
        return None

    recent = df.tail(lookback)
    today = df.iloc[-1]
    avg_vol = recent["volume"].mean()

    pct_chg = (today["close"] - df.iloc[-2]["close"]) / df.iloc[-2]["close"] * 100
    close_position = (today["close"] - today["low"]) / max(today["high"] - today["low"], 0.01)

    if pct_chg > 2 and today["volume"] > avg_vol * vol_mult and close_position > 0.7:
        return {
            "pattern": "Sign of Strength（强势信号）",
            "confidence": "中",
            "description": f"放量上涨{pct_chg:.1f}%，收于高位，聪明钱介入",
            "date": str(df.index[-1])[:10],
        }
    return None


def analyze_wyckoff(df: pd.DataFrame) -> list[dict]:
    """一次识别所有威科夫结构。返回检测到的结构列表。"""
    results = []
    for func in [identify_spring, identify_upthrust, identify_sign_of_strength]:
        try:
            r = func(df)
            if r:
                results.append(r)
        except Exception as e:  # noqa: BLE001
            log.warning("威科夫识别失败: %s", e)
    return results


if __name__ == "__main__":
    # 自测：用模拟数据
    np.random.seed(42)
    dates = pd.date_range("2026-01-01", periods=60)
    close = np.cumsum(np.random.randn(60) * 0.5) + 100
    df = pd.DataFrame({
        "open": close + np.random.randn(60) * 0.2,
        "high": close + np.abs(np.random.randn(60)) * 0.5,
        "low": close - np.abs(np.random.randn(60)) * 0.5,
        "close": close,
        "volume": np.random.randint(1000000, 5000000, 60),
    }, index=dates)
    patterns = analyze_wyckoff(df)
    print(f"检测到 {len(patterns)} 个威科夫结构:")
    for p in patterns:
        print(f"  {p['pattern']}: {p['description']}")
