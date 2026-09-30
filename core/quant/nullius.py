# -*- coding: utf-8 -*-
"""阴性对照回测（模块二 · 证伪优先框架，参考 Nullius）。

Nullius 的核心主张：回测库只是帮你产生一个绩效数字，真正重要的是这个
数字是否经得起证伪。本模块做「阴性对照」：用随机（白噪声）信号替代真实
策略信号，跑 N 次回测，得到随机策略的收益分布；再对比真实策略收益：

- 若真实收益显著高于随机分布（z-score 大、百分位高）→ 策略可能有真本事；
- 若与随机分布无差异 → 标记「不显著」，防止过拟合策略被误信。

纪律：
- 随机信号不读未来：信号在第 t 日收盘后随机生成，成交 t+1 开盘（与真实
  策略同成交纪律，复用 backtest.run_backtest）；
- 固定种子可复现；n_perm 可调（默认 1000，测试用 200 加速）；
- 输出全部为客观评估，不构成投资建议。
"""
from __future__ import annotations

import logging
from typing import Dict, Optional

import numpy as np
import pandas as pd

from core.quant.backtest import BacktestResult, run_backtest

log = logging.getLogger("stockai.quant.nullius")


def _random_signal_rets(df: pd.DataFrame, n: int, seed: int) -> np.ndarray:
    """随机信号策略的收益率数组（n 次）。信号用伯努利噪声（命中率 p=0.5）。"""
    rng = np.random.default_rng(seed)
    out = np.empty(n)
    rets = df["close"].pct_change().dropna().to_numpy()
    for i in range(n):
        sig = rng.integers(0, 2, size=len(df)).astype(float)
        hold = sig[1:]  # t 日信号 → t+1 起生效（对齐成交纪律）
        k = min(len(rets), len(hold))
        if k == 0:
            out[i] = 0.0
            continue
        active = rets[:k][hold[:k] == 1]
        out[i] = float(active.mean()) if len(active) else 0.0
    return out


def negative_control(df: pd.DataFrame, market: str, strategy: str,
                     params: Optional[dict] = None, config=None,
                     n_perm: int = 1000, seed: int = 42) -> dict:
    """阴性对照测试：真实策略收益 vs 随机策略收益分布。

    返回 {real_annual, perm_mean, perm_std, z_score, percentile, n_perm,
          significant, note, detail}：
    - z_score：真实收益离随机分布均值的标准差倍数；
    - percentile：真实收益在随机分布中的百分位（0~100）；
    - significant：z_score>=2 且 percentile>=95 → True；否则 False（不显著）。
    """
    n_bars = len(df)
    min_n = 60
    if n_bars < min_n:
        return {"error": f"数据不足（{n_bars} 根），阴性对照至少需 {min_n} 根"}
    try:
        res: BacktestResult = run_backtest(df, market, strategy, params or None, config)
    except Exception as e:  # noqa: BLE001
        return {"error": f"真实策略回测失败：{e}"}
    real = res.metrics.get("annual_return") or res.metrics.get("total_return") or 0.0

    perm = _random_signal_rets(df, n_perm, seed)
    mean = float(np.mean(perm))
    std = float(np.std(perm))
    z = (real - mean) / std if std > 1e-12 else 0.0
    pct = float((np.sum(perm < real) + 0.5) / n_perm * 100.0)  # 连续校正
    significant = bool(z >= 2.0 and pct >= 95.0)
    verdict = "显著优于随机" if significant else "不显著（未证伪通过）"
    return {
        "real_annual": round(real, 4),
        "perm_mean": round(mean, 4),
        "perm_std": round(std, 4),
        "z_score": round(z, 2),
        "percentile": round(pct, 1),
        "n_perm": n_perm,
        "significant": significant,
        "verdict": verdict,
        "note": (
            "证伪优先：真实策略收益若无法显著优于随机信号分布，则标记为不显著，"
            "防止过拟合策略被误信。z≥2 且百分位≥95 判定为显著。"),
        "detail": {"seed": seed, "bars": n_bars, "strategy": strategy},
    }


if __name__ == "__main__":
    # 自检：构造有趋势数据，验证输出结构
    rng = np.random.default_rng(7)
    n = 200
    close = pd.Series(100 * np.cumprod(1 + rng.normal(0.0005, 0.02, n)))
    df = pd.DataFrame({"open": close, "high": close * 1.01, "low": close * 0.99,
                       "close": close, "volume": rng.integers(1e5, 1e6, n)},
                      index=pd.date_range("2024-01-01", periods=n))
    r = negative_control(df, "CN", "ma_cross", None, None, n_perm=200, seed=1)
    assert "error" not in r, r
    assert 0 <= r["percentile"] <= 100
    print("nullius self-check:", r["verdict"], "z=", r["z_score"], "pct=", r["percentile"])
