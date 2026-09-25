# -*- coding: utf-8 -*-
"""多因子评分体系（纯函数，零网络零依赖，对标 ai-hedge-fund / TradingAgents 的因子层）。

设计哲学：
- 程序负责把每个可量化维度压成 -1.0(强烈空) ~ +1.0(强烈多) 的标准化分，LLM 只做解读；
- 全部用已缓存的日线 DataFrame 计算，历史回放时点自然无前视（bars 已截断）；
- 数据不足/字段缺失的因子记 None，composite 只用"可用因子"加权平均，绝不硬填；
- 估值因子从 funda dict 取 PE/PB（免费源无则 None），与量价因子解耦。

因子清单（v1）：
  momentum  中期动量：20/60 日收益率合成，sigmoid 归一
  trend     趋势：收盘价相对 MA60 的偏离，标准化
  rsi_pos   RSI 位置：均值回归口径——超卖偏多、超买偏空
  volatility 低波奖励：20 日年化波动越低分越高（风险调整视角）
  volume    量能确认：量价同向——价涨量增偏多、价涨量缩偏空
  valuation 估值：PE 越低越值（价值口径；无数据 None）
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from core.quant.indicators import sma


def _clip(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _sigmoid(x: float) -> float:
    if not math.isfinite(x):
        return 0.0
    return 2.0 / (1.0 + math.exp(-x)) - 1.0   # 映射到 (-1, 1)


def _f(x) -> float | None:
    try:
        if x is None or (isinstance(x, float) and (np.isnan(x) or np.isinf(x))):
            return None
        return round(float(x), 4)
    except (TypeError, ValueError):
        return None


def _momentum(close: pd.Series) -> dict:
    if len(close) < 61:
        return {"score": None, "note": "数据不足60日"}
    r20 = float(close.iloc[-1] / close.iloc[-21] - 1.0)
    r60 = float(close.iloc[-1] / close.iloc[-61] - 1.0)
    # 0.5 个标准差的半弹性：月动量0.5%≈0.09，季动量2%≈0.19
    score = _clip(_sigmoid((r20 * 2.0 + r60) * 8.0))
    return {"score": _f(score), "raw_20d_pct": round(r20 * 100, 2),
            "raw_60d_pct": round(r60 * 100, 2),
            "note": f"近20日{r20*100:+.1f}%、近60日{r60*100:+.1f}%"}


def _trend(close: pd.Series) -> dict:
    if len(close) < 61:
        return {"score": None, "note": "数据不足60日"}
    ma60 = float(sma(close, 60).iloc[-1])
    last = float(close.iloc[-1])
    if ma60 == 0 or math.isnan(ma60):
        return {"score": None, "note": "MA60不可用"}
    dev = last / ma60 - 1.0
    score = _clip(_sigmoid(dev * 12.0))   # 偏离MA60约8%→±0.6
    return {"score": _f(score), "raw_above_ma60_pct": round(dev * 100, 2),
            "note": f"收盘{'高于' if dev>=0 else '低于'}MA60 {abs(dev)*100:.1f}%"}


def _rsi_position(close: pd.Series) -> dict:
    from core.quant.indicators import rsi
    if len(close) < 15:
        return {"score": None, "note": "数据不足"}
    v = rsi(close).iloc[-1]
    if math.isnan(v):
        return {"score": None, "note": "RSI不可用"}
    # 均值回归口径：RSI 30→+0.8, 50→0, 70→-0.8
    score = _clip(_sigmoid((50.0 - v) / 7.0))
    tag = "超卖" if v < 30 else ("超买" if v > 70 else "中性区")
    return {"score": _f(score), "raw_rsi14": round(float(v), 1), "note": f"RSI14={v:.0f}（{tag}）"}


def _volatility(close: pd.Series) -> dict:
    if len(close) < 21:
        return {"score": None, "note": "数据不足"}
    ret = close.pct_change().dropna().tail(20)
    if len(ret) < 10:
        return {"score": None, "note": "收益序列不足"}
    ann_vol = float(ret.std() * math.sqrt(252.0))
    # 年化波动 <15% 偏稳(+)，>40% 偏险(-)；用 -(v-0.25) 作中心
    score = _clip(_sigmoid((0.25 - ann_vol) * 6.0))
    return {"score": _f(score), "raw_ann_vol_pct": round(ann_vol * 100, 1),
            "note": f"年化波动约{ann_vol*100:.0f}%（{'低波偏稳' if ann_vol<0.25 else '高波偏险'}）"}


def _volume(close: pd.Series, vol: pd.Series) -> dict:
    if len(close) < 21:
        return {"score": None, "note": "数据不足"}
    price_up = float(close.iloc[-1] / close.iloc[-6] - 1.0)
    v5 = float(vol.tail(5).mean())
    v20 = float(vol.tail(20).mean())
    if v20 == 0 or math.isnan(v20):
        return {"score": None, "note": "量能数据不可用"}
    ratio = v5 / v20
    # 量价同向：涨+放量→多；涨+缩量→空
    price_dir = _sigmoid(price_up * 30.0)
    vol_dir = _clip(_sigmoid((ratio - 1.0) * 4.0))
    score = _clip(price_dir * vol_dir)
    return {"score": _f(score), "raw_vol_ratio": round(ratio, 2),
            "note": f"量比5/20={ratio:.2f}，价{price_up*100:+.1f}%量{'增' if ratio>1 else '缩'}"}


def _valuation(funda: dict | None) -> dict:
    if not funda:
        return {"score": None, "note": "无基本面数据"}
    pe = funda.get("pe") or funda.get("PE") or funda.get("pe_ttm")
    pb = funda.get("pb") or funda.get("PB")
    pe = float(pe) if isinstance(pe, (int, float)) else None
    pb = float(pb) if isinstance(pb, (int, float)) else None
    if pe is None and pb is None:
        return {"score": None, "note": "无PE/PB"}
    # 价值口径：PE=10→+0.7, 25→0, 50→-0.7
    score = None
    if pe and pe > 0:
        score = _clip(_sigmoid((25.0 - pe) / 12.0))
    extra = f"PE={pe}" if pe else ""
    extra += ((" " if extra else "") + f"PB={pb:.2f}") if pb else ""
    return {"score": _f(score), "raw": extra or "无",
            "note": (f"估值{extra}" if score is not None else f"{extra or '估值数据缺'}")}


# 合成权重（仅对可用因子生效，最终归一化）
_WEIGHTS = {
    "momentum": 0.22, "trend": 0.22, "rsi_pos": 0.16,
    "volatility": 0.14, "volume": 0.12, "valuation": 0.14,
}


def compute_factors(bars: pd.DataFrame, funda: dict | None = None) -> dict[str, Any]:
    """输入行情 df（升序，含 close/volume）+ 可选基本面，输出多因子评分。

    返回：
      composite: 0~100（>55 偏多，<45 偏空，区间中性），无任何可用因子时 None；
      factors: {名: {score(-1~1)/raw/note}}；
      consensus: 一句话多空共识；bull/neg: 各因子中偏多/偏空的依据列表。
    """
    if bars is None or len(bars) < 2:
        return {"composite": None, "factors": {}, "consensus": "数据不足"}
    bars = bars.sort_index()
    close, vol = bars["close"], bars["volume"]

    parts = {
        "momentum": _momentum(close),
        "trend": _trend(close),
        "rsi_pos": _rsi_position(close),
        "volatility": _volatility(close),
        "volume": _volume(close, vol),
        "valuation": _valuation(funda),
    }

    used_w = used_s = 0.0
    bull, neg = [], []
    for name, p in parts.items():
        s = p.get("score")
        if s is None:
            continue
        used_w += _WEIGHTS[name]
        used_s += _WEIGHTS[name] * s
        tag = "多" if s > 0.15 else ("空" if s < -0.15 else "中性")
        line = f"[{name}] {p.get('note','')} →{tag}"
        (bull if s > 0.15 else neg if s < -0.15 else list()).append(line)

    composite = None
    if used_w > 0:
        composite = round((used_s / used_w) * 50.0 + 50.0, 1)   # -1~1 → 0~100

    if composite is None:
        consensus = "无可用因子"
    elif composite >= 58:
        consensus = f"多因子综合偏多（{composite:.0f}/100）"
    elif composite <= 42:
        consensus = f"多因子综合偏空（{composite:.0f}/100）"
    else:
        consensus = f"多因子中性（{composite:.0f}/100）"

    return {"composite": composite, "factors": parts,
            "consensus": consensus, "bull_signals": bull, "bear_signals": neg}
