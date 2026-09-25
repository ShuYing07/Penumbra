# -*- coding: utf-8 -*-
"""K 线形态识别（纯函数，无未来函数：只用历史区间内数据）。

先实现 W 底（双底）与 M 头（双顶）两个基础形态；其余形态留 TODO。
所有判定只基于区间内已收盘数据，不偷看未来。
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def _local_extrema(series: np.ndarray, order: int = 5):
    """返回局部极小/极大点索引。order=左右各看 order 根。"""
    mins, maxs = [], []
    n = len(series)
    for i in range(order, n - order):
        win = series[i - order:i + order + 1]
        if series[i] == win.min():
            mins.append(i)
        if series[i] == win.max():
            maxs.append(i)
    return mins, maxs


def _pct(a: float, b: float) -> float:
    return abs(a - b) / b * 100.0 if b else 0.0


def detect_patterns(df: pd.DataFrame, lookback: int = 120,
                    tolerance_pct: float = 3.0) -> list[dict[str, Any]]:
    """识别 K 线形态。

    返回 [{"pattern_name","start_date","end_date","confidence"}]，最新形态优先。
    tolerance_pct：两个底/顶价格差在此百分比内视为"等高"。
    """
    if df is None or len(df) < 30:
        return []
    df = df.sort_index()
    close = df["close"].to_numpy(dtype=float)
    n = len(close)
    start = max(0, n - lookback)
    sub_close = close[start:]
    dates = df.index[start:]

    mins, maxs = _local_extrema(sub_close, order=5)
    out: list[dict[str, Any]] = []

    # W 底（双底）：两个低点价格相近，中间夹一个明显反弹高点
    for a, b in zip(mins[:-1], mins[1:]):
        if b - a < 8:
            continue
        lo_a, lo_b = sub_close[a], sub_close[b]
        mid_seg = sub_close[a:b + 1]
        rebound = mid_seg.max()
        if _pct(lo_a, lo_b) <= tolerance_pct and rebound > max(lo_a, lo_b) * 1.03:
            confidence = 80.0 - _pct(lo_a, lo_b) * 5.0
            out.append({
                "pattern_name": "W底(双底)",
                "start_date": str(dates[a].date()) if hasattr(dates[a], "date") else str(dates[a]),
                "end_date": str(dates[b].date()) if hasattr(dates[b], "date") else str(dates[b]),
                "confidence": round(max(30.0, confidence), 1),
            })

    # M 头（双顶）：两个高点价格相近，中间夹一个明显回落低点
    for a, b in zip(maxs[:-1], maxs[1:]):
        if b - a < 8:
            continue
        hi_a, hi_b = sub_close[a], sub_close[b]
        mid_seg = sub_close[a:b + 1]
        pullback = mid_seg.min()
        if _pct(hi_a, hi_b) <= tolerance_pct and pullback < min(hi_a, hi_b) * 0.97:
            confidence = 80.0 - _pct(hi_a, hi_b) * 5.0
            out.append({
                "pattern_name": "M头(双顶)",
                "start_date": str(dates[a].date()) if hasattr(dates[a], "date") else str(dates[a]),
                "end_date": str(dates[b].date()) if hasattr(dates[b], "date") else str(dates[b]),
                "confidence": round(max(30.0, confidence), 1),
            })

    # TODO: 头肩顶/底、杯柄、三重底/顶、上升/下降三角形
    return out[-10:]
