# -*- coding: utf-8 -*-
"""策略问股引擎（模块二 · 参考 daily_stock_analysis 15 种内置策略）。

提供 15 种内置策略目录：每种策略 = {name, desc, signal(bars)→信号/观点}。
确定性策略（均线、RSI、MACD、布林、动量、突破、量价、趋势、均值回归、
金叉死叉、RSI 超买超卖、成交量、波动率、市盈率、热点/事件）可在合成
数据上直接计算；需事件/舆情数据的策略降级为「数据不可用 + 提示」。
支持多轮追问：`ask_strategy(strategy, question, bars)` 返回结构化答复。
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

import numpy as np
import pandas as pd

log = logging.getLogger("stockai.core.strategies")


# ---------------- 基础指标（确定性） ----------------
def _ma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n).mean()


def _rsi(s: pd.Series, n: int = 14) -> pd.Series:
    d = s.diff()
    up = d.clip(lower=0).rolling(n).mean()
    down = (-d.clip(upper=0)).rolling(n).mean()
    rs = up / down.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50.0)


def _macd(s: pd.Series, fast: int = 12, slow: int = 26, sig: int = 9):
    dif = s.ewm(span=fast, adjust=False).mean() - s.ewm(span=slow, adjust=False).mean()
    dea = dif.ewm(span=sig, adjust=False).mean()
    return dif, dea, (dif - dea)


def _boll(s: pd.Series, n: int = 20, k: float = 2.0):
    mid = s.rolling(n).mean()
    std = s.rolling(n).std()
    return mid + k * std, mid, mid - k * std


# ---------------- 策略目录 ----------------
def _ma_cross(bars: pd.DataFrame) -> Dict[str, object]:
    c = bars["close"].astype(float)
    fast, slow = _ma(c, 5), _ma(c, 20)
    if len(c) < 21 or pd.isna(slow.iloc[-1]):
        return _deg("中性", 0.3, "均线数据不足")
    golden = fast.iloc[-1] > slow.iloc[-1] and fast.iloc[-2] <= slow.iloc[-2]
    death = fast.iloc[-1] < slow.iloc[-1] and fast.iloc[-2] >= slow.iloc[-2]
    if golden:
        return _deg("看多", 0.6, "MA5 上穿 MA20（金叉）", "金叉后关注量能确认")
    if death:
        return _deg("看空", 0.6, "MA5 下穿 MA20（死叉）", "死叉后反弹通常为减仓机会")
    return _deg("看多" if fast.iloc[-1] > slow.iloc[-1] else "看空", 0.4,
                "MA5 位于 MA20 之上（多头排列）" if fast.iloc[-1] > slow.iloc[-1]
                else "MA5 位于 MA20 之下（空头排列）")


def _rsi_signal(bars: pd.DataFrame) -> Dict[str, object]:
    c = bars["close"].astype(float)
    r = _rsi(c).iloc[-1]
    if r >= 70:
        return _deg("看空", 0.6, f"RSI={r:.1f} 超买", "超买区注意回调风险")
    if r <= 30:
        return _deg("看多", 0.6, f"RSI={r:.1f} 超卖", "超卖区存在反弹机会")
    return _deg("中性", 0.4, f"RSI={r:.1f} 中性区间")


def _macd_signal(bars: pd.DataFrame) -> Dict[str, object]:
    c = bars["close"].astype(float)
    dif, dea, hist = _macd(c)
    if pd.isna(dea.iloc[-1]):
        return _deg("中性", 0.3, "MACD 数据不足")
    if dif.iloc[-1] > dea.iloc[-1] and dif.iloc[-2] <= dea.iloc[-2]:
        return _deg("看多", 0.6, "MACD 金叉", "金叉初期关注柱体放大")
    if dif.iloc[-1] < dea.iloc[-1] and dif.iloc[-2] >= dea.iloc[-2]:
        return _deg("看空", 0.6, "MACD 死叉", "死叉后注意减仓")
    return _deg("看多" if dif.iloc[-1] > dea.iloc[-1] else "看空", 0.4,
                "MACD 多头运行" if dif.iloc[-1] > dea.iloc[-1] else "MACD 空头运行")


def _boll_signal(bars: pd.DataFrame) -> Dict[str, object]:
    c = bars["close"].astype(float)
    up, mid, low = _boll(c)
    if pd.isna(low.iloc[-1]):
        return _deg("中性", 0.3, "布林数据不足")
    px = c.iloc[-1]
    if px >= up.iloc[-1]:
        return _deg("看空", 0.55, "价格触及布林上轨", "上轨外注意乖离过大")
    if px <= low.iloc[-1]:
        return _deg("看多", 0.55, "价格触及布林下轨", "下轨外注意超跌反弹")
    return _deg("中性", 0.4, "价格运行于布林中轨附近")


def _momentum(bars: pd.DataFrame) -> Dict[str, object]:
    c = bars["close"].astype(float)
    if len(c) < 22:
        return _deg("中性", 0.3, "动量数据不足")
    m = float(c.iloc[-1] / c.iloc[-21] - 1)
    if m >= 0.1:
        return _deg("看多", 0.55, f"20日动量 {m:+.1%} 强势")
    if m <= -0.1:
        return _deg("看空", 0.55, f"20日动量 {m:+.1%} 弱势")
    return _deg("中性", 0.4, f"20日动量 {m:+.1%} 平稳")


def _breakout(bars: pd.DataFrame) -> Dict[str, object]:
    c = bars["close"].astype(float)
    if len(c) < 21:
        return _deg("中性", 0.3, "突破数据不足")
    hi20 = c.iloc[-21:-1].max()
    lo20 = c.iloc[-21:-1].min()
    px = c.iloc[-1]
    if px > hi20:
        return _deg("看多", 0.6, f"突破20日高点 {hi20:.2f}", "突破需量能配合确认")
    if px < lo20:
        return _deg("看空", 0.6, f"跌破20日低点 {lo20:.2f}", "破位注意止损")
    return _deg("中性", 0.4, "处于20日区间内震荡")


def _volume_price(bars: pd.DataFrame) -> Dict[str, object]:
    c = bars["close"].astype(float)
    v = bars["volume"].astype(float)
    if len(c) < 6:
        return _deg("中性", 0.3, "量价数据不足")
    vr = float(v.iloc[-1] / max(v.iloc[-5:].mean(), 1e-9))
    chg = float(c.iloc[-1] / c.iloc[-2] - 1)
    if chg >= 0.03 and vr >= 1.5:
        return _deg("看多", 0.6, f"放量上涨（量比{vr:.1f}）", "量价齐升，动能良好")
    if chg <= -0.03 and vr >= 1.5:
        return _deg("看空", 0.6, f"放量下跌（量比{vr:.1f}）", "放量下跌警惕出货")
    return _deg("中性", 0.4, f"量价平稳（量比{vr:.1f}）")


def _trend(bars: pd.DataFrame) -> Dict[str, object]:
    c = bars["close"].astype(float)
    if len(c) < 10:
        return _deg("中性", 0.3, "趋势数据不足")
    slope = float(np.polyfit(range(len(c)), c, 1)[0])
    if slope > 0:
        return _deg("看多", 0.55, f"线性趋势向上（斜率 {slope:.2f}）")
    if slope < 0:
        return _deg("看空", 0.55, f"线性趋势向下（斜率 {slope:.2f}）")
    return _deg("中性", 0.4, "趋势平坦")


def _mean_reversion(bars: pd.DataFrame) -> Dict[str, object]:
    c = bars["close"].astype(float)
    if len(c) < 21:
        return _deg("中性", 0.3, "均值回归数据不足")
    ma20 = _ma(c, 20).iloc[-1]
    z = float((c.iloc[-1] - ma20) / max(c.iloc[-20:].std(), 1e-9))
    if z <= -2:
        return _deg("看多", 0.55, f"偏离20日均线 {z:.1f}σ 下方", "超跌回归概率上升")
    if z >= 2:
        return _deg("看空", 0.55, f"偏离20日均线 {z:.1f}σ 上方", "过度上涨有回归压力")
    return _deg("中性", 0.4, "价格围绕均线小幅波动")


def _volatility(bars: pd.DataFrame) -> Dict[str, object]:
    c = bars["close"].astype(float)
    if len(c) < 21:
        return _deg("中性", 0.3, "波动率数据不足")
    vol = float(c.iloc[-20:].pct_change().std())
    if vol >= 0.04:
        return _deg("中性", 0.4, f"20日波动率 {vol:.1%} 偏高", "高波动期控制仓位")
    return _deg("中性", 0.35, f"20日波动率 {vol:.1%} 平稳")


def _rsi_macd_combo(bars: pd.DataFrame) -> Dict[str, object]:
    r = _rsi_signal(bars)
    m = _macd_signal(bars)
    if r["stance"] == "看多" and m["stance"] == "看多":
        return _deg("看多", 0.7, "RSI 与 MACD 共振看多", "双指标共振，信号强化")
    if r["stance"] == "看空" and m["stance"] == "看空":
        return _deg("看空", 0.7, "RSI 与 MACD 共振看空", "双指标共振，信号强化")
    return _deg("中性", 0.35, "RSI 与 MACD 方向分歧", "指标背离，观望为宜")


def _golden_cross(bars: pd.DataFrame) -> Dict[str, object]:
    c = bars["close"].astype(float)
    if len(c) < 51:
        return _deg("中性", 0.3, "均线交叉数据不足")
    m10, m30 = _ma(c, 10), _ma(c, 30)
    golden = m10.iloc[-1] > m30.iloc[-1] and m10.iloc[-2] <= m30.iloc[-2]
    return _deg("看多", 0.6, "MA10 上穿 MA30（中长期金叉）" if golden
                else "均线未现金叉", "中长期金叉后趋势转多" if golden else "")


def _pe_value(bars: pd.DataFrame, extra: Optional[dict] = None) -> Dict[str, object]:
    pe = (extra or {}).get("pe")
    if pe is None:
        return _deg("中性", 0.3, "PE 数据不可用", "需要配置估值数据源")
    if pe < 15:
        return _deg("看多", 0.5, f"PE={pe:.1f} 低于15（相对低估）", "注意低估值陷阱")
    if pe > 40:
        return _deg("看空", 0.4, f"PE={pe:.1f} 高于40（相对高估）", "高估值需要高增长支撑")
    return _deg("中性", 0.4, f"PE={pe:.1f} 处于合理区间")


def _hot_event(bars: pd.DataFrame, extra: Optional[dict] = None) -> Dict[str, object]:
    hot = (extra or {}).get("hot")
    if not hot:
        return _deg("中性", 0.3, "热点/事件数据不可用", "需接入舆情/事件数据源")
    return _deg("看多" if hot.get("sentiment", 0) > 0 else "看空", 0.45,
                f"事件热度 {hot.get('name', '未知')}", "事件驱动行情波动加大")


def _death_cross(bars: pd.DataFrame) -> Dict[str, object]:
    c = bars["close"].astype(float)
    if len(c) < 51:
        return _deg("中性", 0.3, "均线交叉数据不足")
    m10, m30 = _ma(c, 10), _ma(c, 30)
    death = m10.iloc[-1] < m30.iloc[-1] and m10.iloc[-2] >= m30.iloc[-2]
    return _deg("看空", 0.6, "MA10 下穿 MA30（中长期死叉）" if death
                else "均线未现死叉", "中长期死叉后趋势转空" if death else "")


def _deg(stance: str, conf: float, view: str, risk: str = "") -> Dict[str, object]:
    return {"stance": stance, "confidence": conf, "view": view,
            "key_points": [view], "risks": [risk] if risk else []}


STRATEGIES: Dict[str, Dict[str, Any]] = {
    "ma_cross":    {"name": "均线金叉/死叉", "signal": _ma_cross,
                    "desc": "MA5 与 MA20 交叉，判断短期趋势转折"},
    "rsi":         {"name": "RSI 超买超卖", "signal": _rsi_signal,
                    "desc": "RSI(14) 超买(≥70)/超卖(≤30)"},
    "macd":        {"name": "MACD 金叉死叉", "signal": _macd_signal,
                    "desc": "MACD DIF/DEA 交叉与柱体方向"},
    "boll":        {"name": "布林带", "signal": _boll_signal,
                    "desc": "价格相对布林上/中/下轨的位置"},
    "momentum":    {"name": "动量", "signal": _momentum,
                    "desc": "20 日动量强弱"},
    "breakout":    {"name": "突破", "signal": _breakout,
                    "desc": "突破 20 日高/低点"},
    "volume_price":{"name": "量价关系", "signal": _volume_price,
                    "desc": "放量上涨/放量下跌/缩量"},
    "trend":       {"name": "趋势跟随", "signal": _trend,
                    "desc": "线性趋势方向与斜率"},
    "mean_reversion": {"name": "均值回归", "signal": _mean_reversion,
                       "desc": "价格偏离 20 日均线的 σ 幅度"},
    "volatility":  {"name": "波动率", "signal": _volatility,
                    "desc": "20 日收益波动率水平"},
    "rsi_macd":    {"name": "RSI+MACD 共振", "signal": _rsi_macd_combo,
                    "desc": "双指标方向共振/背离"},
    "golden_cross": {"name": "中长期金叉", "signal": _golden_cross,
                     "desc": "MA10 上穿 MA30"},
    "pe":          {"name": "市盈率估值", "signal": _pe_value,
                    "desc": "PE 绝对估值区间"},
    "hot_event":   {"name": "热点/事件", "signal": _hot_event,
                    "desc": "舆情热度与事件驱动"},
    "death_cross": {"name": "中长期死叉", "signal": _death_cross,
                    "desc": "MA10 下穿 MA30"},
}

STRATEGY_KEYS = list(STRATEGIES.keys())


def list_strategies() -> list[dict]:
    return [{"key": k, "name": v["name"], "desc": v["desc"]}
            for k, v in STRATEGIES.items()]


def run_strategy(key: str, bars: pd.DataFrame,
                 extra: Optional[dict] = None) -> Dict[str, object]:
    """运行单一策略，返回信号 + 观点 + 置信度。未知策略返回 error。"""
    spec = STRATEGIES.get(key)
    if not spec:
        return {"error": f"未知策略：{key}（可选 {list(STRATEGIES)}）"}
    try:
        sig = spec["signal"](bars, extra) if key in ("pe", "hot_event") \
            else spec["signal"](bars)
        sig["strategy"] = key
        sig["strategy_name"] = spec["name"]
        return sig
    except Exception as e:  # noqa: BLE001
        return {"error": f"策略 {key} 执行失败：{e}"}


def ask_strategy(key: str, question: str, bars: pd.DataFrame,
                 extra: Optional[dict] = None) -> Dict[str, object]:
    """多轮追问：在策略信号基础上回答自然语言追问。"""
    sig = run_strategy(key, bars, extra)
    if "error" in sig:
        return sig
    ans = (f"【{sig['strategy_name']}】{sig['view']}。"
           f"当前观点：{sig['stance']}（置信度 {sig['confidence']:.0%}）。"
           f"追问「{question or '无'}」将在分析报告中结合该信号展开。")
    return {**sig, "answer": ans}


if __name__ == "__main__":
    rng = np.random.default_rng(5)
    close = pd.Series(100 * np.cumprod(1 + rng.normal(0.001, 0.02, 120)))
    bars = pd.DataFrame({"close": close,
                         "volume": rng.integers(1e5, 5e5, 120)})
    assert len(list_strategies()) == 15, len(list_strategies())
    for k in STRATEGIES:
        r = run_strategy(k, bars, {"pe": 18, "hot": {"name": "AI算力", "sentiment": 1}})
        assert "error" not in r, (k, r)
    r = run_strategy("ma_cross", bars)
    assert r["strategy_name"] == "均线金叉/死叉"
    assert run_strategy("nope", bars)["error"]
    a = ask_strategy("rsi", "现在该买吗？", bars)
    assert "追问" in a["answer"]
    print("strategies self-check ok (15 strategies)")
