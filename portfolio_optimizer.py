# -*- coding: utf-8 -*-
"""组合优化：等权重、最小方差、风险平价（轻量版，不依赖外部库）。"""
from __future__ import annotations

import numpy as np
import pandas as pd


def equal_weight(returns: pd.DataFrame) -> dict:
    """等权重组合。"""
    n = len(returns.columns)
    w = np.ones(n) / n
    return dict(zip(returns.columns, w.tolist()))


def min_variance(returns: pd.DataFrame) -> dict:
    """最小方差组合（解析解，无风险利率=0）。"""
    cov = returns.cov().values
    try:
        inv = np.linalg.pinv(cov)
        ones = np.ones(len(cov))
        w = inv @ ones / (ones @ inv @ ones)
        w = np.clip(w, 0, 1)
        w = w / w.sum()
        return dict(zip(returns.columns, w.tolist()))
    except Exception:
        return equal_weight(returns)


def risk_parity(returns: pd.DataFrame, max_iter: int = 100) -> dict:
    """风险平价（简化版：按波动率倒数分配）。"""
    vol = returns.std().values
    inv_vol = 1.0 / (vol + 1e-8)
    w = inv_vol / inv_vol.sum()
    return dict(zip(returns.columns, w.tolist()))


def portfolio_stats(weights: dict, returns: pd.DataFrame) -> dict:
    """计算组合统计量。"""
    w = np.array([weights.get(c, 0) for c in returns.columns])
    port_ret = (returns * w).sum(axis=1)
    ann_ret = port_ret.mean() * 252
    ann_vol = port_ret.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    return {
        "annual_return": round(float(ann_ret), 4),
        "annual_volatility": round(float(ann_vol), 4),
        "sharpe": round(float(sharpe), 3),
    }


if __name__ == "__main__":
    # 自测：3只股票250天随机收益
    np.random.seed(42)
    rets = pd.DataFrame({
        "600519": np.random.normal(0.001, 0.02, 250),
        "000858": np.random.normal(0.0008, 0.025, 250),
        "300750": np.random.normal(0.0012, 0.03, 250),
    })
    for name, fn in [("等权重", equal_weight), ("最小方差", min_variance), ("风险平价", risk_parity)]:
        w = fn(rets)
        s = portfolio_stats(w, rets)
        print(f"{name}: {s}")
