# -*- coding: utf-8 -*-
"""风险评估师（模块十）：确定性程序计算，不依赖 LLM。

基于日线序列计算：年化波动率、历史法 95% 单日 VaR、区间最大回撤、
压力测试（-10% / -20% 冲击对净值的理论影响），并给出风险等级。

全部为客观统计量，只作数据描述，不构成投资建议。
"""
from __future__ import annotations

import logging
import math

import numpy as np

log = logging.getLogger("stockai.risk_assessor")


def assess_risk(bars, lookback: int = 60) -> dict:
    """bars: 日线 DataFrame（含 close）。返回 {vol_annual_pct, var95_pct,
    max_drawdown_pct, stress, risk_level, note}。"""
    try:
        close = bars["close"].dropna()
        if len(close) < 30:
            return {"risk_level": "数据不足", "note": f"仅 {len(close)} 根K线，无法计算风险指标",
                    "vol_annual_pct": None, "var95_pct": None,
                    "max_drawdown_pct": None, "stress": {}}
        rets = close.pct_change().dropna()
        recent = rets.tail(lookback)
        # 1) 年化波动率（20 日窗口的滚动标准差，按年化 √252）
        vol = float(rets.tail(20).std(ddof=0)) * math.sqrt(252) * 100
        # 2) 历史法 95% 单日 VaR（百分位取 5% 分位，取绝对值）
        var95 = float(np.abs(np.percentile(recent.values, 5))) * 100
        # 3) 最大回撤（全历史窗口）
        peak = close.cummax()
        dd = (close - peak) / peak
        mdd = float(dd.min()) * 100
        # 4) 压力测试：当前价受到 -10% / -20% 冲击后的净值影响
        price = float(close.iloc[-1])
        stress = {
            "shock_minus_10pct": round(price * 0.9, 2),
            "shock_minus_20pct": round(price * 0.8, 2),
            "note": "理论冲击位，仅衡量价格风险暴露",
        }
        # 5) 风险等级（客观阈值）
        if vol >= 40 or mdd <= -30:
            level = "高"
        elif vol >= 25 or mdd <= -20:
            level = "中"
        else:
            level = "低"
        return {
            "vol_annual_pct": round(vol, 2),
            "var95_pct": round(var95, 2),
            "max_drawdown_pct": round(mdd, 2),
            "stress": stress,
            "risk_level": level,
            "note": f"基于近 {lookback} 日收益率统计",
        }
    except Exception as e:  # noqa: BLE001
        log.warning("风险评估计算失败：%s", e)
        return {"risk_level": "不可用", "note": f"计算失败：{type(e).__name__}",
                "vol_annual_pct": None, "var95_pct": None,
                "max_drawdown_pct": None, "stress": {}}
