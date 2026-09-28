# -*- coding: utf-8 -*-
"""组合级风险管理（企业版模块六）：VaR / 压力测试 / 收益归因。

- calculate_var : 历史模拟法 VaR（95/99 分位），支持组合与单标的；
- stress_test    : 情景压力测试（市场下跌 10%/20%、波动放大等）；
- attribution    : 收益归因（各标的对组合收益的贡献分解）；
- 纯 numpy 实现，无新依赖；输出均含"历史统计，不构成投资建议"口径。
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def calculate_var(returns: pd.DataFrame | pd.Series, weights: np.ndarray | None = None,
                  confidence: float = 0.95) -> dict:
    """历史模拟法 VaR。

    - returns : 各标的日收益 DataFrame（列=标的），或单标的 Series；
    - weights : 组合权重（默认等权）；与 returns 列数一致；
    - 返回 {var_pct, cvar_pct, horizon, confidence}，VaR 用正数表示风险。
    """
    if isinstance(returns, pd.Series):
        returns = returns.to_frame()
    returns = returns.dropna()
    if returns.empty or len(returns) < 10:
        raise ValueError("收益数据不足（至少 10 个样本）")
    n = len(returns)
    if weights is None:
        weights = np.full(returns.shape[1], 1.0 / returns.shape[1])
    w = np.asarray(weights, dtype=float)
    w = w / w.sum()
    port_ret = returns.values @ w          # 组合日收益序列
    q = 1 - confidence
    var = float(-np.percentile(port_ret, q * 100))
    cvar = float(-port_ret[port_ret <= -var].mean()) if np.any(port_ret <= -var) else var
    return {"var_pct": round(var * 100, 4),
            "cvar_pct": round(cvar * 100, 4),
            "horizon": "1日", "confidence": confidence,
            "samples": n}


def stress_test(returns: pd.DataFrame | pd.Series, weights: np.ndarray | None = None,
                scenarios: list[dict] | None = None) -> list[dict]:
    """情景压力测试：模拟市场下跌对组合的冲击。

    默认场景：-5% / -10% / -20% / +10%（beta 敏感度 = 标的对市场 beta，
    可用历史收益与市场收益回归估算，缺省取 1.0）。
    """
    if scenarios is None:
        scenarios = [{"name": "温和下跌", "market_shift": -0.05},
                     {"name": "中度下跌", "market_shift": -0.10},
                     {"name": "极端下跌", "market_shift": -0.20},
                     {"name": "反弹",     "market_shift": +0.10}]
    if isinstance(returns, pd.Series):
        returns = returns.to_frame()
    if weights is None:
        weights = np.full(returns.shape[1], 1.0 / returns.shape[1])
    w = np.asarray(weights, dtype=float)
    w = w / w.sum()
    out = []
    for sc in scenarios:
        shift = sc["market_shift"]
        # 简化 beta=1：组合损失 ≈ 市场跌幅；可用历史回归改进
        port_impact = shift * w.sum()
        out.append({"scenario": sc["name"], "market_shift_pct": shift * 100,
                    "portfolio_impact_pct": round(port_impact * 100, 2),
                    "note": "历史统计模拟，不构成投资建议"})
    return out


def attribution(returns: pd.DataFrame, weights: np.ndarray | None = None) -> pd.DataFrame:
    """收益归因：各标的对组合累计收益的贡献分解。

    返回 DataFrame：标的 / 权重 / 区间收益 / 贡献(权重×收益)。
    """
    if weights is None:
        weights = np.full(returns.shape[1], 1.0 / returns.shape[1])
    w = np.asarray(weights, dtype=float)
    w = w / w.sum()
    period_ret = (1 + returns.fillna(0)).prod() - 1   # 各标的区间累计收益
    contrib = period_ret.values * w
    df = pd.DataFrame({
        "ticker": returns.columns,
        "weight": np.round(w, 4),
        "period_return_pct": np.round(period_ret.values * 100, 2),
        "contribution_pct": np.round(contrib * 100, 2),
    })
    return df.sort_values("contribution_pct", ascending=False).reset_index(drop=True)
