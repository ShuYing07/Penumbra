# -*- coding: utf-8 -*-
"""多标的组合回测：各标的独立策略回测 → 日收益加权 → 权重漂移 + 定期再平衡。

口径与简化（v1）：
1. 每个标的跑一次 run_backtest（统一策略/参数、标的层已含真实费率），取策略与
   buy_hold 基准两条日收益；组合层与基准层用**相同目标权重+相同再平衡规则**，
   故超额收益=标的内策略择时的纯增益，权重配置贡献被公平扣除；
2. 公共区间=各标的数据首尾交集，日历=各市场交易日并集，某市场休市日其收益记 0；
3. 再平衡 none/month/quarter/year：调仓日收盘后权重拉回目标，次日生效；
   非调仓日权重随相对涨跌漂移（买入持有式）；
4. v1 不计再平衡层换手费（标的层费用已计；ETF 漂移通常较小），不做风险平价。
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from core.quant.backtest import (TRADING_DAYS, BacktestConfig, compute_metrics,
                                  run_backtest)

REBALANCE_CHOICES = ("none", "month", "quarter", "year")
_MIN_DAYS = 30


@dataclass
class HoldingSpec:
    ticker: str
    weight: float = 1.0


@dataclass
class PortfolioResult:
    tickers: list[str]
    weights: dict[str, float]
    strategy: str
    params: dict
    rebalance: str
    start: str
    end: str
    equity: pd.DataFrame                       # strategy/benchmark 组合净值
    holdings: list[dict] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    benchmark_metrics: dict = field(default_factory=dict)
    weight_track: pd.DataFrame | None = None


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------
def _normalize_weights(tickers: list[str], raw: list[float] | None) -> np.ndarray:
    if not tickers:
        raise ValueError("标的列表为空")
    if raw is None:
        w = np.ones(len(tickers))
    else:
        if len(raw) != len(tickers):
            raise ValueError(f"权重数量 {len(raw)} 与标的数量 {len(tickers)} 不一致")
        w = np.asarray(raw, dtype=float)
    if np.any(w < 0) or w.sum() <= 0:
        raise ValueError("权重必须 ≥0 且总和 > 0")
    return w / w.sum()


def _rebalance_days(dates: pd.DatetimeIndex, mode: str) -> set:
    """再平衡日（交易日历上的周期首日）。"""
    if mode not in REBALANCE_CHOICES:
        raise ValueError(f"未知再平衡周期 {mode}（可选 {REBALANCE_CHOICES}）")
    if mode == "none":
        return set()
    first_month = {"month": None, "quarter": {1, 4, 7, 10}, "year": {1}}[mode]
    days: set = set()
    prev_ym = None
    for d in dates:
        ym = (d.year, d.month)
        if prev_ym is None or ym[0] != prev_ym[0] or ym[1] != prev_ym[1]:
            if first_month is None or d.month in first_month:
                days.add(d)
        prev_ym = ym
    return days


def _holder_stats(ret: pd.Series) -> dict:
    """单标的公共区间内的风险收益（ret=日收益率，首日0）。"""
    r = ret.fillna(0.0)
    total = float((1 + r).prod() - 1)
    days = len(r)
    years = days / TRADING_DAYS
    ann = (1 + total) ** (1 / years) - 1 if years > 0 and (1 + total) > 0 else 0.0
    vol = float(r.std() * np.sqrt(TRADING_DAYS)) if days > 1 else 0.0
    nav = (1 + r).cumprod()
    mdd = float((nav / nav.cummax() - 1).min())
    sharpe = float(r.mean() / r.std() * np.sqrt(TRADING_DAYS)) if days > 1 and r.std() > 0 else 0.0
    return {"total_return_pct": round(total * 100, 2),
            "annual_return_pct": round(ann * 100, 2),
            "volatility_pct": round(vol * 100, 2),
            "max_drawdown_pct": round(mdd * 100, 2),
            "sharpe": round(sharpe, 3)}


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------
def run_portfolio(specs: list[HoldingSpec],
                  strategy: str = "buy_hold",
                  params: dict | None = None,
                  rebalance: str = "none",
                  init_capital: float = 1_000_000.0,
                  start: str | None = None, end: str | None = None,
                  bars_map: dict[str, pd.DataFrame] | None = None) -> PortfolioResult:
    """跑多标的组合回测。bars_map 非空时直接使用（零联网，测试用）。"""
    tickers = [s.ticker.upper() for s in specs]
    w0 = _normalize_weights(tickers, [s.weight for s in specs])

    # 1) 各标的独立回测（全量数据跑，保证指标预热；公共区间在净值层裁）
    from core.data import service

    strat_rets: dict[str, pd.Series] = {}
    bench_rets: dict[str, pd.Series] = {}
    markets: dict[str, str] = {}
    used_params: dict = {}
    for tk in tickers:
        market = service.market_of(tk)
        if market == "UNKNOWN":
            raise ValueError(f"无法识别标的: {tk}")
        markets[tk] = market
        df = bars_map[tk] if bars_map is not None else service.get_daily(tk)[0]
        cfg = BacktestConfig(ticker=tk, market=market, init_capital=init_capital)
        res = run_backtest(df, market, strategy, params=params, config=cfg)
        used_params = res.params
        eq = res.equity.copy()
        eq.index = pd.to_datetime(eq.index)
        # 首日收益须显式保留（含买入费：nav 首日略<1），否则 pct_change 会把费用丢掉、
        # 经复利放大；组合加权在收益层进行，成本由此正确传导
        ns = eq["strategy"].astype(float) / init_capital
        nb = eq["benchmark"].astype(float) / init_capital
        rs = ns.pct_change()
        rb = nb.pct_change()
        rs.iloc[0] = ns.iloc[0] - 1.0
        rb.iloc[0] = nb.iloc[0] - 1.0
        strat_rets[tk] = rs
        bench_rets[tk] = rb

    # 2) 公共区间 + 交易日并集
    starts = [s.index[0] for s in strat_rets.values()]
    ends = [s.index[-1] for s in strat_rets.values()]
    c_start = max(starts)
    c_end = min(ends)
    if start:
        c_start = max(c_start, pd.Timestamp(start))
    if end:
        c_end = min(c_end, pd.Timestamp(end))
    union = pd.DatetimeIndex(sorted(set().union(*[set(s.index) for s in strat_rets.values()])))
    union = union[(union >= c_start) & (union <= c_end)]
    if len(union) < _MIN_DAYS:
        raise ValueError(f"公共交易日仅 {len(union)} 根（需≥{_MIN_DAYS}），请选数据区间重叠更多的标的")

    RS = pd.DataFrame({tk: strat_rets[tk].reindex(union).fillna(0.0) for tk in tickers},
                      index=union)
    RB = pd.DataFrame({tk: bench_rets[tk].reindex(union).fillna(0.0) for tk in tickers},
                      index=union)
    rbal = _rebalance_days(union, rebalance)

    # 3) 权重递推 + 组合净值（策略组合与基准组合同规则）
    w = w0.copy()
    wb = w0.copy()
    nav_s, nav_b = 1.0, 1.0
    eq_s, eq_b, tracks = [], [], []
    for d in union:
        tracks.append(w.copy())   # 当日开盘实际承担收益的权重
        rs = RS.loc[d].to_numpy(float)
        rb = RB.loc[d].to_numpy(float)
        rp, bp = float(w @ rs), float(wb @ rb)
        nav_s *= 1 + rp
        nav_b *= 1 + bp
        w = w * (1 + rs) / (1 + rp) if (1 + rp) > 0 else w0.copy()
        wb = wb * (1 + rb) / (1 + bp) if (1 + bp) > 0 else w0.copy()
        eq_s.append(nav_s)
        eq_b.append(nav_b)
        if d in rbal:  # 收盘调回目标，次日开盘权重（即下一轮 track）生效
            w = w0.copy()
            wb = w0.copy()

    equity = pd.DataFrame(
        {"strategy": np.round(np.asarray(eq_s) * init_capital, 2),
         "benchmark": np.round(np.asarray(eq_b) * init_capital, 2),
         "cash": 0.0, "market_value": np.round(np.asarray(eq_s) * init_capital, 2)},
        index=union.strftime("%Y-%m-%d"))

    # 4) 组合与基准指标（口径同单标的回测；组合层无成交流水）
    cfg = BacktestConfig(ticker="PORTFOLIO", market="CN", init_capital=init_capital)
    metrics = compute_metrics(equity, pd.DataFrame(columns=["fee"]), [], cfg)
    bench_metrics = _bench_metrics(equity, init_capital)
    metrics["benchmark_return_pct"] = bench_metrics["total_return_pct"]
    metrics["excess_return_pct"] = round(
        metrics["total_return_pct"] - bench_metrics["total_return_pct"], 2)

    # 5) 各标的贡献（公共区间内各自策略收益/风险）
    holdings = []
    for tk, wi in zip(tickers, w0):
        st = _holder_stats(RS[tk])
        st.update({"ticker": tk, "market": markets[tk], "weight_pct": round(wi * 100, 1),
                   "buy_hold_pct": _holder_stats(RB[tk])["total_return_pct"]})
        holdings.append(st)

    return PortfolioResult(
        tickers=tickers, weights={tk: round(float(wi), 4) for tk, wi in zip(tickers, w0)},
        strategy=strategy, params=used_params, rebalance=rebalance,
        start=union[0].strftime("%Y-%m-%d"), end=union[-1].strftime("%Y-%m-%d"),
        equity=equity, holdings=holdings, metrics=metrics,
        benchmark_metrics=bench_metrics,
        weight_track=pd.DataFrame(tracks, index=union.strftime("%Y-%m-%d"),
                                  columns=tickers))


def _bench_metrics(equity: pd.DataFrame, init: float) -> dict:
    """基准列单独算一份风险指标（compute_metrics 的基准列只取了收益率）。"""
    s = equity["benchmark"].astype(float)
    r = s.pct_change().fillna(0.0)
    days = len(s)
    years = days / TRADING_DAYS
    total = float(s.iloc[-1] / init - 1)
    ann = (s.iloc[-1] / init) ** (1 / years) - 1 if years > 0 and s.iloc[-1] > 0 else 0.0
    mdd = float((s / s.cummax() - 1).min())
    vol = float(r.std() * np.sqrt(TRADING_DAYS))
    sharpe = float(r.mean() / r.std() * np.sqrt(TRADING_DAYS)) if days > 1 and r.std() > 0 else 0.0
    return {"total_return_pct": round(total * 100, 2),
            "annual_return_pct": round(ann * 100, 2),
            "volatility_pct": round(vol * 100, 2),
            "max_drawdown_pct": round(mdd * 100, 2),
            "sharpe": round(sharpe, 3)}
