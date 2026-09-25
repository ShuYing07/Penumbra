# -*- coding: utf-8 -*-
"""市场状态（regime）判别：用长周期均线结构判断牛/熊/震荡，输出仓位调节系数。

设计说明：
- 对标 MoE 路由思想——不同市场状态下风险预算不同。熊市收缩仓位、震荡降杠杆、牛市放开；
- v1 用标的自身日线长周期结构（MA200/MA50/斜率）近似 regime，纯函数零网络零依赖；
  （升级方向：未来接入沪深300/标普500大盘指数作市场状态，更贴近"大盘牛熊"定义。）
- 数据不足 200 根时保守判 range，不惩罚、不冒进；
- position_multiplier 是给风控层的确定性系数（程序算，非 LLM 观点）。
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from core.quant.indicators import sma


def classify_regime(bars: pd.DataFrame) -> dict:
    """返回 {regime, note, position_multiplier}。

    regime:
      bull   多头：收盘>MA200 且 MA50>MA200 且 MA200 近20日走平向上
      bear   空头：收盘<MA200 且 MA50<MA200
      range  震荡/其他：介于两者之间，或数据不足
    """
    if bars is None or len(bars) < 60:
        return {"regime": "range", "note": "数据不足，按震荡中性处理", "position_multiplier": 0.75}

    close = bars.sort_index()["close"]
    last = float(close.iloc[-1])
    ma200 = sma(close, 200)
    ma50 = sma(close, 50)

    # 短于200日：用 MA50 相对现价粗判，仍中性
    if len(close) < 200 or math.isnan(float(ma200.iloc[-1])):
        ma50v = float(ma50.iloc[-1])
        if math.isnan(ma50v):
            return {"regime": "range", "note": "中短周期均线不可用，按震荡中性",
                    "position_multiplier": 0.75}
        if last > ma50v * 1.05:
            return {"regime": "bull", "note": f"短期强势（收盘高于MA50 {((last/ma50v-1)*100):.1f}%）",
                    "position_multiplier": 1.0}
        if last < ma50v * 0.95:
            return {"regime": "range", "note": f"短期偏弱（收盘低于MA50 {((1-last/ma50v)*100):.1f}%）",
                    "position_multiplier": 0.6}
        return {"regime": "range", "note": "围绕MA50震荡", "position_multiplier": 0.75}

    ma200v = float(ma200.iloc[-1])
    ma50v = float(ma50.iloc[-1])
    # MA200 斜率：近20日 vs 现在
    ma200_slope = None
    if len(close) >= 220 and not math.isnan(float(ma200.iloc[-20])):
        ma200_slope = (ma200v - float(ma200.iloc[-20])) / float(ma200.iloc[-20])

    above200 = last > ma200v
    golden_stack = ma50v > ma200v

    if above200 and golden_stack:
        sl = "" if ma200_slope is None else ("，长期均线向上" if ma200_slope > 0 else "，长期均线走平")
        return {"regime": "bull",
                "note": f"多头格局：收盘>MA200 且 MA50>MA200{sl}",
                "position_multiplier": 1.0}
    if (not above200) and (not golden_stack):
        return {"regime": "bear",
                "note": "空头格局：收盘<MA200 且 MA50<MA200，收缩风险预算",
                "position_multiplier": 0.5}
    return {"regime": "range",
            "note": f"震荡格局（现价/MA200={last/ma200v:.2f}, MA50/MA200={ma50v/ma200v:.2f}）",
            "position_multiplier": 0.75}
