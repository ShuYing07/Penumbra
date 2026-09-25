# -*- coding: utf-8 -*-
"""Kronos金融时序基础模型：K线形态特征提取（轻量版，无GPU也可运行）。"""
from __future__ import annotations

import logging

log = logging.getLogger("stockai.kronos")


def get_kline_pattern(df) -> dict:
    """基于K线数据识别基础形态（趋势/震荡/反转）。
    轻量规则版：不依赖大型模型，用均线和波动率判断。
    """
    if df is None or len(df) < 30:
        return {"pattern": "数据不足", "confidence": 0.0}

    close = df["close"]
    ma5 = close.rolling(5).mean().iloc[-1]
    ma20 = close.rolling(20).mean().iloc[-1]
    ma60 = close.rolling(60).mean().iloc[-1] if len(close) >= 60 else ma20
    latest = close.iloc[-1]

    # 判断趋势
    if ma5 > ma20 > ma60 and latest > ma5:
        pattern = "上升趋势"
        confidence = 0.8
    elif ma5 < ma20 < ma60 and latest < ma5:
        pattern = "下降趋势"
        confidence = 0.8
    else:
        pattern = "震荡整理"
        confidence = 0.5

    # 判断波动率
    returns = close.pct_change().dropna()
    volatility = returns.tail(20).std() * (252 ** 0.5)
    if volatility > 0.4:
        pattern += "（高波动）"
    elif volatility < 0.15:
        pattern += "（低波动）"

    return {
        "pattern": pattern,
        "confidence": confidence,
        "volatility": round(float(volatility), 3),
        "ma5": round(float(ma5), 2),
        "ma20": round(float(ma20), 2),
    }
