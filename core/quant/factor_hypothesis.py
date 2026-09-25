# -*- coding: utf-8 -*-
"""因子假设自动生成与验证。

让Agent基于当前数据自动提出可验证的假设，然后调用回测引擎检验。
不做盲目因子挖掘，每个假设都有明确的经济逻辑。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

log = logging.getLogger("stockai.factor_hyp")


@dataclass
class Hypothesis:
    """一个可验证的因子假设。"""
    name: str
    description: str
    logic: str           # 经济逻辑
    signal_col: str      # 信号列名
    direction: int       # 1=信号看多, -1=信号看空
    hold_days: int = 5   # 持有期


def generate_hypotheses(bars: pd.DataFrame) -> list[Hypothesis]:
    """基于当前数据自动生成候选假设。

    不做暴力搜索，只生成有经济逻辑的假设：
    1. 量价突破：放量突破20日均线
    2. 超卖反弹：RSI<30后反弹
    3. 动量延续：20日动量>0且量比>1
    """
    hyps = []
    close = bars["close"]
    volume = bars["volume"] if "volume" in bars else pd.Series(1, index=bars.index)

    # 假设1：放量突破20日均线
    sma20 = close.rolling(20).mean()
    vol_ma20 = volume.rolling(20).mean()
    break_signal = ((close > sma20) & (volume > vol_ma20 * 1.5)).astype(int)
    hyps.append(Hypothesis(
        name="vol_breakout_ma20",
        description="放量突破20日均线",
        logic="成交量放大1.5倍+价格站上20日均线，说明资金主动进场",
        signal_col="_sig_vol_break",
        direction=1,
        hold_days=5,
    ))
    bars["_sig_vol_break"] = break_signal

    # 假设2：RSI超卖反弹
    from core.quant.indicators import rsi
    r = rsi(close, 14)
    oversold_signal = (r < 30).astype(int)
    hyps.append(Hypothesis(
        name="rsi_oversold_bounce",
        description="RSI<30超卖后买入",
        logic="RSI低于30表明短期超卖，存在均值回归反弹可能",
        signal_col="_sig_rsi_os",
        direction=1,
        hold_days=5,
    ))
    bars["_sig_rsi_os"] = oversold_signal

    # 假设3：动量延续
    mom20 = close / close.shift(20) - 1
    vol_ratio = volume / vol_ma20
    momentum_signal = ((mom20 > 0.05) & (vol_ratio > 1.0)).astype(int)
    hyps.append(Hypothesis(
        name="momentum_continue",
        description="20日动量>5%且量能正常",
        logic="上涨趋势中量能维持，趋势可能延续",
        signal_col="_sig_momentum",
        direction=1,
        hold_days=10,
    ))
    bars["_sig_momentum"] = momentum_signal

    return hyps


def validate_hypothesis(bars: pd.DataFrame, hyp: Hypothesis) -> dict:
    """验证一个假设：统计信号触发后N日的收益分布。

    返回：{信号次数, 平均收益, 胜率, t统计量, 是否显著}
    """
    sig = bars[hyp.signal_col].values
    close = bars["close"].values

    # 找到所有信号触发点
    entries = np.where(sig[:-hyp.hold_days] == 1)[0]
    if len(entries) < 5:
        return {"signals": len(entries), "mean_return": None,
                "win_rate": None, "t_stat": None, "significant": False,
                "note": "信号次数不足（<5），统计不可靠"}

    # 计算持有期收益
    returns = []
    for idx in entries:
        entry_price = close[idx + 1]  # 次日开盘等价
        exit_price = close[idx + 1 + hyp.hold_days]
        if entry_price > 0:
            returns.append(exit_price / entry_price - 1)

    returns = np.array(returns)
    mean_ret = float(np.mean(returns))
    std_ret = float(np.std(returns)) if len(returns) > 1 else 0
    n = len(returns)
    t_stat = mean_ret / (std_ret / np.sqrt(n)) if std_ret > 0 else 0
    win_rate = float(np.mean(returns > 0))

    # 简单显著性判断（t>1.645 ≈ p<0.05单尾）
    significant = abs(t_stat) > 1.645 and n >= 10

    return {
        "signals": n,
        "mean_return_pct": round(mean_ret * 100, 2),
        "win_rate_pct": round(win_rate * 100, 1),
        "t_stat": round(t_stat, 2),
        "significant": significant,
        "hold_days": hyp.hold_days,
    }


def run_factor_screening(bars: pd.DataFrame) -> list[dict]:
    """跑全部假设并返回排序后的结果。"""
    df = bars.copy()
    hyps = generate_hypotheses(df)
    results = []
    for hyp in hyps:
        r = validate_hypothesis(df, hyp)
        results.append({
            "name": hyp.name,
            "description": hyp.description,
            "logic": hyp.logic,
            **r,
        })
    results.sort(key=lambda x: abs(x.get("t_stat") or 0), reverse=True)
    return results
