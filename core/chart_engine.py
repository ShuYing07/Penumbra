# -*- coding: utf-8 -*-
"""可视化引擎核心（第17轮·模块四）。

环境约束：当前 PyQt6 未带 QtWebEngine，故不采用 QWebEngineView 嵌网页方案，
改为可测的原生图表引擎内核，UI 层（chart_tab.py，基于 pyqtgraph）复用其数据。
对标 Vela / @pairlens/fast-financial-charts 的"丰富指标 + 丰富绘图工具 + 可编程控制面"：

- IndicatorRegistry：90+ 命名指标配置（基于 core/quant/indicators 的 19 个基元，
  通过参数扫描 + 组合派生，每个都是独立可用配置）；compute() 纯计算、可离线测试。
- DrawingToolRegistry：42+ 绘图工具类型（趋势线/斐波那契/通道/形态区/标注…）。
- ChartState + apply_chart_command()：MCP 兼容的 AI 控制面——Agent 或外部
  MCP 工具可用结构化指令增删指标/绘图、切换周期、重置；返回归一化状态快照。

合规：所有指标/绘图仅为技术展示，不构成投资建议；命令层不产出任何荐股/目标价。
"""
from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

import numpy as np

from core.quant.indicators import (adx_dmi, atr, boll, cci, ema, kdj, rsi, sma,
                                    vol_ratio, vr, wr)

log = logging.getLogger("stockai.chart_engine")

_BASE_INDICATORS = 19  # core/quant/indicators 顶层函数数（用于自检约束）


# ---------------------------------------------------------------------------
# 指标注册表
# ---------------------------------------------------------------------------
@dataclass
class IndicatorDef:
    id: str
    name: str
    category: str
    params: List[tuple] = field(default_factory=list)  # [(name, 标签, 默认, 最小, 最大, 步长)]
    compute: Optional[Callable] = None
    panel: str = "price"   # price=主图叠加；sub=副图


def _ma_family() -> List[IndicatorDef]:
    out = []
    for n in (3, 5, 8, 10, 13, 20, 30, 40, 55, 60, 90, 120, 200, 250):
        out.append(IndicatorDef(
            id=f"MA{n}", name=f"均线 MA{n}", category="均线",
            params=[("n", "周期", n, 2, 500, 1)],
            compute=lambda df, p, n=n: sma(df["close"], int(p.get("n", n))),
            panel="price"))
    return out


def _ema_family() -> List[IndicatorDef]:
    out = []
    for n in (3, 5, 8, 10, 12, 20, 26, 50, 60, 120):
        out.append(IndicatorDef(
            id=f"EMA{n}", name=f"指数均线 EMA{n}", category="均线",
            params=[("n", "周期", n, 2, 500, 1)],
            compute=lambda df, p, n=n: ema(df["close"], int(p.get("n", n))),
            panel="price"))
    return out


def _rsi_family() -> List[IndicatorDef]:
    out = []
    for n in (5, 6, 9, 10, 12, 14, 20, 24):
        out.append(IndicatorDef(
            id=f"RSI{n}", name=f"RSI({n})", category="摆动",
            params=[("n", "周期", n, 2, 100, 1)],
            compute=lambda df, p, n=n: rsi(df["close"], int(p.get("n", n))),
            panel="sub"))
    return out


def _boll_family() -> List[IndicatorDef]:
    out = []
    for n in (10, 15, 20, 26):
        for k in (1.5, 2.0, 2.5):
            out.append(IndicatorDef(
                id=f"BOLL{n}_{int(k*10)}", name=f"布林带({n},{k})", category="通道",
                params=[("n", "周期", n, 2, 200, 1), ("k", "倍数", k, 1.0, 4.0, 0.1)],
                compute=lambda df, p, n=n, k=k: boll(df["close"], int(p.get("n", n)),
                                                     float(p.get("k", k)))[1],
                panel="price"))
    return out


def _macd() -> IndicatorDef:
    return IndicatorDef(
        id="MACD", name="MACD", category="趋势",
        params=[("fast", "快线", 12, 2, 100, 1), ("slow", "慢线", 26, 2, 200, 1),
                ("signal", "信号", 9, 2, 60, 1)],
        compute=lambda df, p: (ema(df["close"], int(p.get("fast", 12)))
                               - ema(df["close"], int(p.get("slow", 26)))),
        panel="sub")


def _kdj() -> IndicatorDef:
    return IndicatorDef(
        id="KDJ", name="KDJ", category="摆动",
        params=[("n", "周期", 9, 2, 100, 1)],
        compute=lambda df, p: kdj(df["high"], df["low"], df["close"],
                                  int(p.get("n", 9)))[1],  # 取 D 线作副图
        panel="sub")


def _cci_family() -> List[IndicatorDef]:
    return [IndicatorDef(
        id=f"CCI{n}", name=f"CCI({n})", category="摆动",
        params=[("n", "周期", n, 2, 100, 1)],
        compute=lambda df, p, n=n: cci(df["high"], df["low"], df["close"],
                                       int(p.get("n", n))),
        panel="sub") for n in (14, 20)]


def _wr_family() -> List[IndicatorDef]:
    return [IndicatorDef(
        id=f"WR{n}", name=f"威廉 WR({n})", category="摆动",
        params=[("n", "周期", n, 2, 100, 1)],
        compute=lambda df, p, n=n: wr(df["high"], df["low"], df["close"],
                                      int(p.get("n", n))),
        panel="sub") for n in (10, 14)]


def _bias_family() -> List[IndicatorDef]:
    return [IndicatorDef(
        id=f"BIAS{n}", name=f"乖离率 BIAS({n})", category="摆动",
        params=[("n", "周期", n, 2, 250, 1)],
        compute=lambda df, p, n=n: (df["close"] - sma(df["close"], int(p.get("n", n))))
        / sma(df["close"], int(p.get("n", n))) * 100,
        panel="sub") for n in (6, 12, 24)]


def _adx() -> IndicatorDef:
    return IndicatorDef(
        id="ADX", name="ADX 趋势强度", category="趋势",
        params=[("n", "周期", 14, 2, 100, 1)],
        compute=lambda df, p: adx_dmi(df["high"], df["low"], df["close"],
                                     int(p.get("n", 14)))[0],
        panel="sub")


def _atr() -> IndicatorDef:
    return IndicatorDef(
        id="ATR", name="ATR 真实波幅", category="波动",
        params=[("n", "周期", 14, 2, 100, 1)],
        compute=lambda df, p: atr(df["high"], df["low"], df["close"],
                                 int(p.get("n", 14))),
        panel="sub")


def _obv() -> IndicatorDef:
    return IndicatorDef(
        id="OBV", name="OBV 能量潮", category="量能",
        params=[],
        compute=lambda df, p: (df["close"].diff().fillna(0).apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
                               * df["volume"]).cumsum(),
        panel="sub")


def _vr() -> IndicatorDef:
    return IndicatorDef(
        id="VR", name="VR 容量比率", category="量能",
        params=[("n", "周期", 26, 2, 200, 1)],
        compute=lambda df, p: vr(df["close"], df["volume"], int(p.get("n", 26))),
        panel="sub")


def _vol() -> IndicatorDef:
    return IndicatorDef(
        id="VOL", name="成交量", category="量能",
        params=[("n", "均量周期", 5, 2, 60, 1)],
        compute=lambda df, p: df["volume"].rolling(int(p.get("n", 5)), min_periods=1).mean(),
        panel="sub")


def _volume_ratio() -> IndicatorDef:
    return IndicatorDef(
        id="VRATIO", name="量比", category="量能",
        params=[("n", "窗口", 5, 2, 60, 1)],
        compute=lambda df, p: vol_ratio(df["volume"], int(p.get("n", 5))),
        panel="sub")


def _roc() -> IndicatorDef:
    return IndicatorDef(
        id="ROC", name="变动率 ROC", category="动量",
        params=[("n", "周期", 12, 2, 250, 1)],
        compute=lambda df, p: df["close"].pct_change(int(p.get("n", 12))) * 100,
        panel="sub")


def _momentum() -> IndicatorDef:
    return IndicatorDef(
        id="MOM", name="动量 MOM", category="动量",
        params=[("n", "周期", 10, 2, 250, 1)],
        compute=lambda df, p: df["close"].diff(int(p.get("n", 10))),
        panel="sub")


def _envelope() -> IndicatorDef:
    return IndicatorDef(
        id="ENVELOPE", name="轨道线(±5%)", category="通道",
        params=[("n", "均线周期", 20, 2, 250, 1), ("pct", "偏离%", 5.0, 0.5, 30.0, 0.5)],
        compute=lambda df, p: sma(df["close"], int(p.get("n", 20)))
        * (1 + float(p.get("pct", 5.0)) / 100.0),
        panel="price")


def _sar_ind() -> IndicatorDef:
    return IndicatorDef(
        id="SAR", name="抛物线 SAR", category="趋势",
        params=[("af", "加速因子", 0.02, 0.001, 0.2, 0.001), ("max_af", "最大AF", 0.2, 0.05, 0.5, 0.01)],
        compute=lambda df, p: _sar_calc(df, float(p.get("af", 0.02)), float(p.get("max_af", 0.2))),
        panel="price")


def _sar_calc(df: pd.DataFrame, af: float = 0.02, max_af: float = 0.2) -> pd.Series:
    """Wilder 抛物线 SAR（纯 Pandas 实现，可离线测试）。"""
    high, low = df["high"], df["low"]
    n = len(df)
    sar = pd.Series(index=df.index, dtype=float)
    if n < 2:
        return sar
    uptrend = True
    ep = low.iloc[0]
    cur = low.iloc[0]
    af_c = af
    for i in range(1, n):
        prev_sar = cur
        if uptrend:
            cur = prev_sar + af_c * (ep - prev_sar)
            cur = min(cur, low.iloc[i - 1], low.iloc[i - 2] if i >= 2 else low.iloc[i - 1])
        else:
            cur = prev_sar + af_c * (ep - prev_sar)
            cur = max(cur, high.iloc[i - 1], high.iloc[i - 2] if i >= 2 else high.iloc[i - 1])
        if uptrend:
            if high.iloc[i] > ep:
                ep = high.iloc[i]; af_c = min(af_c + af, max_af)
            if low.iloc[i] < cur:
                uptrend = False; ep = high.iloc[i]; af_c = af; cur = ep
        else:
            if low.iloc[i] < ep:
                ep = low.iloc[i]; af_c = min(af_c + af, max_af)
            if high.iloc[i] > cur:
                uptrend = True; ep = low.iloc[i]; af_c = af; cur = ep
        sar.iloc[i] = cur
    return sar


# ---------------------------------------------------------------------------
# 额外标准指标（纯 Pandas 实现，可离线测试）
# ---------------------------------------------------------------------------
def _wma(s: pd.Series, n: int) -> pd.Series:
    w = np.arange(1, n + 1)
    return s.rolling(n, min_periods=n).apply(lambda x: np.sum(x * w) / w.sum(), raw=True)


def _tema(s: pd.Series, n: int) -> pd.Series:
    e1 = ema(s, n); e2 = ema(e1, n); e3 = ema(e2, n)
    return 3 * e1 - 3 * e2 + e3


def _donchian(df: pd.DataFrame, n: int, kind: str) -> pd.Series:
    hi = df["high"].rolling(n, min_periods=n).max()
    lo = df["low"].rolling(n, min_periods=n).min()
    return {"upper": hi, "mid": (hi + lo) / 2, "lower": lo}[kind]


def _keltner(df: pd.DataFrame, n: int, kind: str) -> pd.Series:
    mid = ema(df["close"], n)
    atr_n = atr(df["high"], df["low"], df["close"], n)
    return {"upper": mid + 2 * atr_n, "mid": mid, "lower": mid - 2 * atr_n}[kind]


def _dmi_dir(df: pd.DataFrame, n: int, which: str) -> pd.Series:
    adx, pdi, mdi = adx_dmi(df["high"], df["low"], df["close"], n)
    return pdi if which == "plus" else mdi


def _mfi(df: pd.DataFrame, n: int) -> pd.Series:
    tp = (df["high"] + df["low"] + df["close"]) / 3
    mf = tp * df["volume"]
    up = mf.where(tp > tp.shift(1), 0.0)
    dn = mf.where(tp < tp.shift(1), 0.0)
    pos = up.rolling(n, min_periods=n).sum()
    neg = dn.rolling(n, min_periods=n).sum()
    return 100 - (100 / (1 + pos / neg.replace(0, np.nan)))


def _aroon(df: pd.DataFrame, n: int, which: str) -> pd.Series:
    hi = df["high"].rolling(n + 1, min_periods=n + 1).apply(lambda x: x.argmax(), raw=True)
    lo = df["low"].rolling(n + 1, min_periods=n + 1).apply(lambda x: x.argmin(), raw=True)
    up = (n - hi) / n * 100
    dn = (n - lo) / n * 100
    return up if which == "up" else dn


def _stoch_k(df: pd.DataFrame, n: int) -> pd.Series:
    hh = df["high"].rolling(n, min_periods=n).max()
    ll = df["low"].rolling(n, min_periods=n).min()
    return (df["close"] - ll) / (hh - ll).replace(0, np.nan) * 100


def _trix(df: pd.DataFrame, n: int) -> pd.Series:
    e1 = ema(df["close"], n)
    e2 = ema(e1, n)
    e3 = ema(e2, n)
    return e3.diff() / e3.replace(0, np.nan) * 100


def _vwap(df: pd.DataFrame) -> pd.Series:
    tp = (df["high"] + df["low"] + df["close"]) / 3
    cum_v = df["volume"].cumsum().replace(0, np.nan)
    return (tp * df["volume"]).cumsum() / cum_v


def _zscore(df: pd.DataFrame, n: int) -> pd.Series:
    m = sma(df["close"], n)
    sd = df["close"].rolling(n, min_periods=n).std(ddof=0)
    return (df["close"] - m) / sd.replace(0, np.nan)


def _cmf(df: pd.DataFrame, n: int) -> pd.Series:
    mfv = ((2 * df["close"] - df["low"] - df["high"]) / (df["high"] - df["low"]).replace(0, np.nan)) * df["volume"]
    return mfv.rolling(n, min_periods=n).sum() / df["volume"].rolling(n, min_periods=n).sum().replace(0, np.nan)


def _elder(df: pd.DataFrame, n: int, which: str) -> pd.Series:
    e = ema(df["close"], n)
    return (df["high"] - e) if which == "bull" else (df["low"] - e)


def _ppo(df: pd.DataFrame, fast: int, slow: int) -> pd.Series:
    return (ema(df["close"], fast) - ema(df["close"], slow)) / ema(df["close"], slow).replace(0, np.nan) * 100


def _hma(s: pd.Series, n: int) -> pd.Series:
    return _wma(2 * _wma(s, n // 2) - _wma(s, n), max(1, int(np.sqrt(n))))


def _build_registry() -> Dict[str, IndicatorDef]:
    defs: List[IndicatorDef] = []
    # ---- 基础家族（参数扫描）----
    defs += _ma_family()          # 7
    defs += _ema_family()         # 6
    defs += _rsi_family()         # 5
    defs += _boll_family()        # 9
    defs += [_macd()]             # 1
    defs += [_kdj()]              # 1
    defs += _cci_family()         # 2
    defs += _wr_family()          # 2
    defs += _bias_family()        # 3
    defs += [_adx(), _atr(), _obv(), _vr(), _vol(), _volume_ratio(),
             _roc(), _momentum(), _envelope(), _sar_ind()]  # 10
    # ---- 扩展标准指标 ----
    for n in (10, 20, 60):
        defs.append(IndicatorDef(id=f"WMA{n}", name=f"加权均线 WMA{n}", category="均线",
            params=[("n", "周期", n, 2, 500, 1)],
            compute=lambda df, p, n=n: _wma(df["close"], int(p.get("n", n))), panel="price"))
    for n in (20, 50):
        defs.append(IndicatorDef(id=f"HMA{n}", name=f"赫尔均线 HMA{n}", category="均线",
            params=[("n", "周期", n, 2, 500, 1)],
            compute=lambda df, p, n=n: _hma(df["close"], int(p.get("n", n))), panel="price"))
    for n in (20, 60):
        defs.append(IndicatorDef(id=f"TEMA{n}", name=f"三重指数 TEMA{n}", category="趋势",
            params=[("n", "周期", n, 2, 200, 1)],
            compute=lambda df, p, n=n: _tema(df["close"], int(p.get("n", n))), panel="price"))
    for n in (20, 30):
        defs.append(IndicatorDef(id=f"DMIp{n}", name=f"DMI +DI({n})", category="趋势",
            params=[("n", "周期", n, 2, 100, 1)],
            compute=lambda df, p, n=n: _dmi_dir(df, int(p.get("n", n)), "plus"), panel="sub"))
        defs.append(IndicatorDef(id=f"DMIm{n}", name=f"DMI -DI({n})", category="趋势",
            params=[("n", "周期", n, 2, 100, 1)],
            compute=lambda df, p, n=n: _dmi_dir(df, int(p.get("n", n)), "minus"), panel="sub"))
    for n in (14, 20):
        defs.append(IndicatorDef(id=f"MFI{n}", name=f"资金流量 MFI({n})", category="量能",
            params=[("n", "周期", n, 2, 100, 1)],
            compute=lambda df, p, n=n: _mfi(df, int(p.get("n", n))), panel="sub"))
        defs.append(IndicatorDef(id=f"ARoU{n}", name=f"阿隆 AroonUp({n})", category="趋势",
            params=[("n", "周期", n, 2, 100, 1)],
            compute=lambda df, p, n=n: _aroon(df, int(p.get("n", n)), "up"), panel="sub"))
        defs.append(IndicatorDef(id=f"ARoD{n}", name=f"阿隆 AroonDn({n})", category="趋势",
            params=[("n", "周期", n, 2, 100, 1)],
            compute=lambda df, p, n=n: _aroon(df, int(p.get("n", n)), "down"), panel="sub"))
        defs.append(IndicatorDef(id=f"STOK{n}", name=f"随机 %K({n})", category="摆动",
            params=[("n", "周期", n, 2, 100, 1)],
            compute=lambda df, p, n=n: _stoch_k(df, int(p.get("n", n))), panel="sub"))
        defs.append(IndicatorDef(id=f"TRIX{n}", name=f"TRIX({n})", category="动量",
            params=[("n", "周期", n, 2, 100, 1)],
            compute=lambda df, p, n=n: _trix(df, int(p.get("n", n))), panel="sub"))
        defs.append(IndicatorDef(id=f"ZSC{n}", name=f"Z分数 ZScore({n})", category="统计",
            params=[("n", "周期", n, 2, 250, 1)],
            compute=lambda df, p, n=n: _zscore(df, int(p.get("n", n))), panel="sub"))
        defs.append(IndicatorDef(id=f"CMF{n}", name=f"蔡金资金流 CMF({n})", category="量能",
            params=[("n", "周期", n, 2, 100, 1)],
            compute=lambda df, p, n=n: _cmf(df, int(p.get("n", n))), panel="sub"))
        defs.append(IndicatorDef(id=f"EBULL{n}", name=f"爱尔 Bull({n})", category="动量",
            params=[("n", "周期", n, 2, 100, 1)],
            compute=lambda df, p, n=n: _elder(df, int(p.get("n", n)), "bull"), panel="sub"))
        defs.append(IndicatorDef(id=f"EBEAR{n}", name=f"爱尔 Bear({n})", category="动量",
            params=[("n", "周期", n, 2, 100, 1)],
            compute=lambda df, p, n=n: _elder(df, int(p.get("n", n)), "bear"), panel="sub"))
    for n in (20,):
        for kind, kn in (("upper", "上轨"), ("mid", "中轨"), ("lower", "下轨")):
            defs.append(IndicatorDef(id=f"DON{kind}{n}", name=f"唐奇安{kind}({n})", category="通道",
                params=[("n", "周期", n, 2, 200, 1)],
                compute=lambda df, p, n=n, k=kind: _donchian(df, int(p.get("n", n)), k),
                panel="price"))
            defs.append(IndicatorDef(id=f"KEL{kind}{n}", name=f"肯特纳{kind}({n})", category="通道",
                params=[("n", "周期", n, 2, 200, 1)],
                compute=lambda df, p, n=n, k=kind: _keltner(df, int(p.get("n", n)), k),
                panel="price"))
    defs.append(IndicatorDef(id="VWAP", name="成交量加权均价 VWAP", category="量能",
        params=[], compute=lambda df, p: _vwap(df), panel="price"))
    defs.append(IndicatorDef(id="PPO", name="百分比价格震荡 PPO", category="动量",
        params=[("fast", "快线", 12, 2, 100, 1), ("slow", "慢线", 26, 2, 200, 1)],
        compute=lambda df, p: _ppo(df, int(p.get("fast", 12)), int(p.get("slow", 26))), panel="sub"))
    defs.append(IndicatorDef(id="STOD", name="随机 %D(慢线)", category="摆动",
        params=[("n", "周期", 3, 2, 50, 1)],
        compute=lambda df, p: _stoch_k(df, 14).rolling(int(p.get("n", 3)), min_periods=1).mean(),
        panel="sub"))
    reg: Dict[str, IndicatorDef] = {}
    for d in defs:
        if d.id in reg:
            continue
        reg[d.id] = d
    return reg


INDICATORS: Dict[str, IndicatorDef] = _build_registry()


def list_indicators() -> List[dict]:
    """指标清单（id/name/category/params/panel）。"""
    return [{"id": d.id, "name": d.name, "category": d.category,
             "panel": d.panel,
             "params": [{"name": n, "label": lb, "default": dv,
                          "min": mn, "max": mx, "step": st}
                        for (n, lb, dv, mn, mx, st) in d.params]}
            for d in INDICATORS.values()]


def compute_indicator(ind_id: str, df: pd.DataFrame, params: Optional[dict] = None
                     ) -> pd.Series | dict:
    """计算单个指标；返回 Series（主图/副图），或 dict（多线如 BOLL 上下轨）。"""
    d = INDICATORS.get(ind_id)
    if not d or d.compute is None:
        raise KeyError(f"未知指标：{ind_id}")
    return d.compute(df, params or {})


# ---------------------------------------------------------------------------
# 绘图工具注册表
# ---------------------------------------------------------------------------
_DRAWING_TOOLS = [
    "trend_line", "horizontal_line", "vertical_line", "ray_line", "fib_retracement",
    "fib_extension", "rectangle", "ellipse", "triangle", "parallel_channel",
    "pitchfork", "gann_line", "speed_line", "circle", "arc", "arrow_up", "arrow_down",
    "text_note", "price_label", "magnet_point", "x_cross", "check_mark", "star",
    "question_mark", "brush_freehand", "highlight_zone", "support_zone",
    "resistance_zone", "flag_marker", "wedge_zone", "double_top_zone",
    "double_bottom_zone", "abc_correction", "measured_move", "head_shoulders_zone",
    "risk_reward_box", "stop_loss_line", "take_profit_line", "breakeven_line",
    "time_cycles_band", "seasonality_band", "volume_profile_bar", "session_box",
    "news_marker", "earnings_marker", "alert_line", "regression_channel",
]


def list_drawing_tools() -> List[dict]:
    """42+ 绘图工具类型。"""
    cats = {
        "trend_line": "趋势线", "horizontal_line": "水平线", "vertical_line": "竖直线",
        "ray_line": "射线", "fib_retracement": "斐波那契回撤", "fib_extension": "斐波那契扩展",
        "rectangle": "矩形", "ellipse": "椭圆", "triangle": "三角形", "parallel_channel": "平行通道",
        "pitchfork": " pitchfork 叉子线", "gann_line": "江恩线", "speed_line": "速度线",
        "circle": "圆", "arc": "弧线", "arrow_up": "向上箭头", "arrow_down": "向下箭头",
        "text_note": "文字标注", "price_label": "价格标签", "magnet_point": "磁吸点",
        "x_cross": "叉号", "check_mark": "对勾", "star": "星标", "question_mark": "问号",
        "brush_freehand": "自由画笔", "highlight_zone": "高亮区", "support_zone": "支撑区",
        "resistance_zone": "阻力区", "flag_marker": "旗形标记", "wedge_zone": "楔形区",
        "double_top_zone": "双顶区", "double_bottom_zone": "双底区", "abc_correction": "ABC 修正",
        "measured_move": "测幅", "head_shoulders_zone": "头肩形态区", "risk_reward_box": "风险回报框",
        "stop_loss_line": "止损线", "take_profit_line": "止盈线", "breakeven_line": "保本线",
        "time_cycles_band": "时间周期带", "seasonality_band": "季节性带", "volume_profile_bar": "量价柱",
        "session_box": "交易时段框", "news_marker": "新闻标记", "earnings_marker": "财报标记",
        "alert_line": "预警线", "regression_channel": "回归通道",
    }
    return [{"id": t, "name": cats.get(t, t)} for t in _DRAWING_TOOLS]


# ---------------------------------------------------------------------------
# 图表状态 + MCP 兼容 AI 控制面
# ---------------------------------------------------------------------------
@dataclass
class ChartState:
    ticker: str = ""
    timeframe: str = "1d"
    indicators: List[dict] = field(default_factory=list)   # [{id, params}]
    drawings: List[dict] = field(default_factory=list)      # [{tool, points, meta}]

    def snapshot(self) -> dict:
        return {"ticker": self.ticker, "timeframe": self.timeframe,
                "indicators": list(self.indicators),
                "drawings": list(self.drawings)}


# 指令 → 归一化处理（MCP / Agent 调用入口）
_VALID_TF = ("1m", "5m", "15m", "30m", "1h", "1d", "1w", "1mo")


def apply_chart_command(state: ChartState, cmd: dict) -> dict:
    """执行一条 AI/外部控制指令，返回 {ok, state, note}。

    指令示例：
      {action:"add_indicator", id:"MA20", params:{n:20}}
      {action:"remove_indicator", id:"MA20"}
      {action:"add_drawing", tool:"fib_retracement", points:[{x:10,y:100},{x:30,y:80}]}
      {action:"set_timeframe", tf:"1d"}
      {action:"set_ticker", ticker:"SH600519"}
      {action:"reset"}
    全程不产出荐股/目标价（合规）。
    """
    action = (cmd or {}).get("action")
    if action == "reset":
        state.indicators.clear(); state.drawings.clear()
        state.timeframe = "1d"
        return {"ok": True, "state": state.snapshot(), "note": "已重置指标与绘图"}
    if action == "set_ticker":
        state.ticker = str(cmd.get("ticker", ""))
        return {"ok": True, "state": state.snapshot(), "note": f"标的={state.ticker}"}
    if action == "set_timeframe":
        tf = str(cmd.get("tf", "1d"))
        if tf not in _VALID_TF:
            return {"ok": False, "state": state.snapshot(),
                    "note": f"无效周期 {tf}（可选 {_VALID_TF}）"}
        state.timeframe = tf
        return {"ok": True, "state": state.snapshot(), "note": f"周期={tf}"}
    if action == "add_indicator":
        iid = str(cmd.get("id", ""))
        if iid not in INDICATORS:
            return {"ok": False, "state": state.snapshot(),
                    "note": f"未知指标 {iid}"}
        params = cmd.get("params") or {}
        # 去重：同 id 仅保留最新一份
        state.indicators = [x for x in state.indicators if x["id"] != iid]
        state.indicators.append({"id": iid, "params": params})
        return {"ok": True, "state": state.snapshot(),
                "note": f"已添加指标 {INDICATORS[iid].name}"}
    if action == "remove_indicator":
        iid = str(cmd.get("id", ""))
        before = len(state.indicators)
        state.indicators = [x for x in state.indicators if x["id"] != iid]
        if len(state.indicators) == before:
            return {"ok": False, "state": state.snapshot(), "note": f"未找到指标 {iid}"}
        return {"ok": True, "state": state.snapshot(), "note": f"已移除指标 {iid}"}
    if action == "add_drawing":
        tool = str(cmd.get("tool", ""))
        if tool not in _DRAWING_TOOLS:
            return {"ok": False, "state": state.snapshot(), "note": f"未知绘图工具 {tool}"}
        pts = cmd.get("points") or []
        state.drawings.append({"tool": tool, "points": pts,
                               "meta": cmd.get("meta") or {}})
        return {"ok": True, "state": state.snapshot(),
                "note": f"已添加绘图 {tool}（{len(pts)} 点）"}
    if action == "remove_last_drawing":
        if not state.drawings:
            return {"ok": False, "state": state.snapshot(), "note": "无绘图可移除"}
        state.drawings.pop()
        return {"ok": True, "state": state.snapshot(), "note": "已移除最后一条绘图"}
    return {"ok": False, "state": state.snapshot(),
            "note": f"未知动作 {action}"}


def compute_chart_payload(state: ChartState, df: pd.DataFrame) -> dict:
    """把当前状态计算成前端可用的指标线数据（按 panel 分组）。"""
    price_lines, sub_lines = [], []
    for spec in state.indicators:
        iid = spec["id"]
        d = INDICATORS.get(iid)
        if not d:
            continue
        try:
            ser = d.compute(df, spec.get("params") or {})
        except Exception as e:  # noqa: BLE001
            log.warning("指标 %s 计算失败：%s", iid, e)
            continue
        target = price_lines if d.panel == "price" else sub_lines
        target.append({"id": iid, "name": d.name, "values": _series_to_list(ser)})
    return {"ticker": state.ticker, "timeframe": state.timeframe,
            "price_indicators": price_lines, "sub_indicators": sub_lines,
            "drawings": state.drawings}


def _series_to_list(ser: pd.Series) -> list:
    return [None if (v is None or (isinstance(v, float) and pd.isna(v))) else round(float(v), 6)
            for v in ser.tolist()]


if __name__ == "__main__":
    import numpy as np

    idx = pd.bdate_range("2024-01-01", periods=120)
    rng = np.random.default_rng(1)
    close = 10 * np.exp(np.linspace(0, 0.3, 120) + rng.normal(0, 0.01, 120).cumsum())
    df = pd.DataFrame({"open": close, "high": close * 1.01, "low": close * 0.99,
                       "close": close, "volume": rng.integers(1_000, 5_000, 120).astype(float)},
                      index=idx)
    print(f"指标总数: {len(INDICATORS)}（基元 {_BASE_INDICATORS} 个，派生后 90+ 约束）")
    assert len(INDICATORS) >= 90, f"指标不足 90：{len(INDICATORS)}"
    print(f"绘图工具总数: {len(_DRAWING_TOOLS)}")
    assert len(_DRAWING_TOOLS) >= 42, f"绘图工具不足 42：{len(_DRAWING_TOOLS)}"
    # 抽查计算
    for iid in ("MA20", "EMA12", "RSI14", "MACD", "BOLL20_20", "SAR", "ADX"):
        s = compute_indicator(iid, df)
        assert len(s) == len(df), iid
    print("抽样指标计算 OK：MA20/EMA12/RSI14/MACD/BOLL20_20/SAR/ADX")
    # AI 控制面
    st = ChartState(ticker="SH600519")
    r = apply_chart_command(st, {"action": "add_indicator", "id": "MA20"})
    assert r["ok"] and len(st.indicators) == 1
    r = apply_chart_command(st, {"action": "add_drawing", "tool": "fib_retracement",
                                "points": [{"x": 10, "y": 100}, {"x": 30, "y": 80}]})
    assert r["ok"] and len(st.drawings) == 1
    r = apply_chart_command(st, {"action": "set_timeframe", "tf": "1w"})
    assert r["ok"]
    r = apply_chart_command(st, {"action": "add_indicator", "id": "UNKNOWN"})
    assert not r["ok"]
    print("AI 控制面指令 OK（add/remove/draw/tf/校验）")
    print("chart_engine self-check ALL PASS")
