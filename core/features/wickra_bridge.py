# -*- coding: utf-8 -*-
"""流式特征桥（模块三 · 参考 wickra-feature-store）。

wickra 提供 497 个 O(1) 流式指标，但为可选依赖（需手动安装）。
本桥接层：
- 已安装 wickra → 尝试调用其指标接口（存在则优先）；
- 未安装 → 降级到内置确定性指标（RSI/MACD/MA/ATR/布林/量比/动量/
  波动率/乖离率/振幅等 12 项），保证 Agent 工具层始终有特征输入。

`compute_features(bars)` 返回 {feature_name: value}；全部无新依赖。
"""
from __future__ import annotations

import logging
from typing import Dict, Optional

import numpy as np
import pandas as pd

log = logging.getLogger("stockai.core.features")

try:
    import wickra  # type: ignore  # 可选依赖（需手动安装）
    _WICKRA_AVAILABLE = True
except Exception:  # noqa: BLE001
    wickra = None  # type: ignore
    _WICKRA_AVAILABLE = False


def wickra_available() -> bool:
    return _WICKRA_AVAILABLE


def _rsi(s: pd.Series, n: int = 14) -> float:
    d = s.diff()
    up = d.clip(lower=0).rolling(n).mean()
    down = (-d.clip(upper=0)).rolling(n).mean()
    rs = up / down.replace(0, np.nan)
    v = (100 - 100 / (1 + rs)).iloc[-1]
    return float(v) if pd.notna(v) else 50.0


def _macd(s: pd.Series):
    dif = s.ewm(span=12, adjust=False).mean() - s.ewm(span=26, adjust=False).mean()
    dea = dif.ewm(span=9, adjust=False).mean()
    return float(dif.iloc[-1] - dea.iloc[-1])


def _atr(bars: pd.DataFrame, n: int = 14) -> float:
    h, l, c = bars["high"].astype(float), bars["low"].astype(float), \
        bars["close"].astype(float)
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    v = tr.rolling(n).mean().iloc[-1]
    return float(v) if pd.notna(v) else 0.0


def compute_features(bars: pd.DataFrame) -> Dict[str, float]:
    """计算流式特征矩阵（内置 12 项；wickra 可用时优先）。"""
    if _WICKRA_AVAILABLE and bars is not None:
        try:
            out = wickra.features(bars)  # type: ignore
            if isinstance(out, dict) and out:
                return {k: float(v) for k, v in out.items() if v is not None}
        except Exception as e:  # noqa: BLE001
            log.warning("wickra 计算失败，降级内置指标：%s", e)
    if bars is None or len(bars) < 30:
        return {}
    c = bars["close"].astype(float)
    v = bars["volume"].astype(float)
    ret = c.pct_change().dropna()
    ma5, ma20 = c.rolling(5).mean(), c.rolling(20).mean()
    feats: Dict[str, float] = {
        "rsi14": _rsi(c),
        "macd_hist": _macd(c),
        "ma5": float(ma5.iloc[-1]),
        "ma20": float(ma20.iloc[-1]),
        "close_ma20_bias": float(c.iloc[-1] / ma20.iloc[-1] - 1),
        "atr14": _atr(bars),
        "vol_ratio": float(v.iloc[-1] / max(v.iloc[-5:].mean(), 1e-9)),
        "mom20": float(c.iloc[-1] / c.iloc[-21] - 1) if len(c) >= 21 else 0.0,
        "vol20": float(ret.iloc[-20:].std()) if len(ret) >= 20 else 0.0,
        "amplitude": float((bars["high"].iloc[-1] - bars["low"].iloc[-1])
                           / c.iloc[-1]),
        "turnover_est": float(v.iloc[-1] / max(v.iloc[-20:].mean(), 1e-9)),
        "close": float(c.iloc[-1]),
    }
    return {k: (float(v) if np.isfinite(v) else 0.0) for k, v in feats.items()}


if __name__ == "__main__":
    rng = np.random.default_rng(2)
    close = pd.Series(100 * np.cumprod(1 + rng.normal(0.001, 0.02, 80)))
    bars = pd.DataFrame({"close": close,
                         "high": close * 1.01, "low": close * 0.99,
                         "volume": rng.integers(1e5, 5e5, 80)})
    f = compute_features(bars)
    assert set(f) >= {"rsi14", "macd_hist", "ma5", "ma20", "atr14", "vol20"}
    assert 0 <= f["rsi14"] <= 100
    assert compute_features(bars.iloc[:10]) == {}   # 样本不足 → 空
    print(f"wickra_bridge self-check ok (wickra={'yes' if _WICKRA_AVAILABLE else 'no'})")
