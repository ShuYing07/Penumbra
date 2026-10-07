# -*- coding: utf-8 -*-
"""批量回测网格 + 组合感知运行（2026-10 翻新 · 模块三）。

参考 TradingAgents v0.5.0「backtesting over a ticker and date grid +
portfolio-aware runs」：单一标的单段区间的回测结论极不稳定，必须放到
「多标的 × 多时间窗口 × 多策略」的网格上检验，并在**组合层面**聚合
（组合净值 ≠ 各标的净值平均，须按权重合成后重新计算风险指标）。

能力：
1. `run_grid()`：标的 × 策略 × 日期窗口的三维网格批量回测，
   逐格返回指标，失败格单独记录（不中断整批）；
2. `portfolio_aggregate()`：组合感知聚合——按权重合成组合净值曲线后
   **重新计算**年化/最大回撤/夏普（而非对各标的指标取平均，那是错的）；
3. `grid_summary()`：按策略/按标的/按窗口三个维度汇总（胜率、中位收益、
   最差窗口），用于判断结论是「普遍成立」还是「个别样本偶然」。

全部确定性、可复现，单标的回测复用 core.quant.backtest.run_backtest。
"""
from __future__ import annotations

import sys
import os
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

import numpy as np
import pandas as pd

from core.quant.backtest import run_backtest

TRADING_DAYS = 252


def _slice(df: pd.DataFrame, start: Optional[str], end: Optional[str]
           ) -> pd.DataFrame:
    out = df
    if start:
        out = out[out.index >= pd.Timestamp(start)]
    if end:
        out = out[out.index <= pd.Timestamp(end)]
    return out


def run_grid(bars_map: Dict[str, pd.DataFrame],
             strategies: Sequence[str],
             windows: Optional[Sequence[Tuple[Optional[str], Optional[str]]]] = None,
             market: str = "CN",
             params_map: Optional[Dict[str, Dict[str, Any]]] = None,
             min_bars: int = 120) -> Dict[str, Any]:
    """三维网格批量回测：标的 × 策略 × 日期窗口。

    返回 {cells:[{code, strategy, window, metrics, bars}], failures:[...], count}。
    """
    windows = list(windows) if windows else [(None, None)]
    params_map = params_map or {}
    cells: List[Dict[str, Any]] = []
    failures: List[Dict[str, Any]] = []
    equity_map: Dict[str, pd.Series] = {}

    for code, df in (bars_map or {}).items():
        if df is None or len(df) == 0:
            failures.append({"code": code, "strategy": "-", "window": "-",
                             "error": "无数据"})
            continue
        for strat in strategies:
            for (s, e) in windows:
                sub = _slice(df, s, e)
                label = f"{s or '全段'}~{e or '全段'}"
                if len(sub) < min_bars:
                    failures.append({"code": code, "strategy": strat,
                                     "window": label,
                                     "error": f"数据不足（{len(sub)}<{min_bars}）"})
                    continue
                try:
                    res = run_backtest(sub, market, strat,
                                       params_map.get(strat), None)
                except Exception as ex:  # noqa: BLE001  单格失败不中断整批
                    failures.append({"code": code, "strategy": strat,
                                     "window": label, "error": str(ex)[:160]})
                    continue
                m = dict(res.metrics)
                cells.append({"code": code, "strategy": strat, "window": label,
                              "bars": int(len(sub)), "metrics": m})
                key = f"{code}|{strat}|{label}"
                equity_map[key] = res.equity["strategy"].astype(float)
    return {"cells": cells, "failures": failures, "count": len(cells),
            "_equity": equity_map}


def portfolio_aggregate(equity_map: Dict[str, pd.Series],
                        weights: Optional[Dict[str, float]] = None
                        ) -> Dict[str, Any]:
    """组合感知聚合：按权重合成净值曲线后重算风险指标。

    注意：组合指标必须基于合成后的净值重算，不能对各标的指标取平均
    （平均法会低估回撤、高估夏普——分散化的收益正是来自合成而非平均）。
    """
    if not equity_map:
        return {"metrics": {}, "weights": {}, "n": 0}
    # 对齐到共同交易日（交集），缺失按前值填充
    frames = [s.rename(k) for k, s in equity_map.items()]
    df = pd.concat(frames, axis=1).sort_index().ffill().dropna(how="any")
    if df.empty:
        return {"metrics": {}, "weights": {}, "n": len(equity_map)}
    if weights:
        w = pd.Series({k: float(weights.get(k, 0.0)) for k in df.columns})
        if w.sum() <= 0:
            w = pd.Series(1.0 / len(df.columns), index=df.columns)
        else:
            w = w / w.sum()
    else:
        w = pd.Series(1.0 / len(df.columns), index=df.columns)
    # 归一化到 1 起点后按权重合成
    norm = df / df.iloc[0]
    port = (norm * w).sum(axis=1)

    rets = port.pct_change().dropna()
    total = float(port.iloc[-1] - 1.0) * 100.0
    years = max(len(port) / TRADING_DAYS, 1e-9)
    annual = float((port.iloc[-1]) ** (1 / years) - 1.0) * 100.0
    mdd = float((port / port.cummax() - 1.0).min()) * 100.0
    vol = float(rets.std() * np.sqrt(TRADING_DAYS)) * 100.0 if len(rets) else 0.0
    sharpe = float(rets.mean() / rets.std() * np.sqrt(TRADING_DAYS)) \
        if len(rets) and rets.std() > 1e-12 else 0.0
    return {
        "weights": {k: round(float(v), 4) for k, v in w.items()},
        "n": int(len(df.columns)),
        "bars": int(len(port)),
        "equity": port,
        "metrics": {"total_return_pct": round(total, 4),
                    "annual_return_pct": round(annual, 4),
                    "max_drawdown_pct": round(mdd, 4),
                    "volatility_pct": round(vol, 4),
                    "sharpe": round(sharpe, 4)},
        "note": "组合指标基于权重合成后的净值重算（非各标的指标平均）",
    }


def grid_summary(grid: Dict[str, Any]) -> Dict[str, Any]:
    """按策略/标的/窗口三维汇总：胜率、中位收益、最差窗口。"""
    cells = grid.get("cells") or []
    if not cells:
        return {"by_strategy": {}, "by_code": {}, "by_window": {}, "count": 0}

    def _agg(key_fn, name: str) -> Dict[str, Any]:
        buckets: Dict[str, List[float]] = {}
        for c in cells:
            r = (c.get("metrics") or {}).get("total_return_pct")
            if r is None:
                continue
            buckets.setdefault(key_fn(c), []).append(float(r))
        out: Dict[str, Any] = {}
        for k, vals in buckets.items():
            arr = np.asarray(vals, dtype=float)
            out[k] = {
                "n": int(len(arr)),
                "median_return_pct": round(float(np.median(arr)), 3),
                "mean_return_pct": round(float(arr.mean()), 3),
                "win_rate_pct": round(float((arr > 0).mean() * 100), 1),
                "worst_return_pct": round(float(arr.min()), 3),
                "best_return_pct": round(float(arr.max()), 3),
            }
        return out

    return {
        "by_strategy": _agg(lambda c: c["strategy"], "strategy"),
        "by_code": _agg(lambda c: c["code"], "code"),
        "by_window": _agg(lambda c: c["window"], "window"),
        "count": len(cells),
        "failures": len(grid.get("failures") or []),
        "interp": "胜率=网格中收益为正的比例；中位收益比均值更抗极端样本",
    }


if __name__ == "__main__":
    rng = np.random.default_rng(21)
    codes = ("A", "B", "C")
    bars_map = {}
    for i, code in enumerate(codes):
        n = 700
        idx = pd.bdate_range("2021-01-01", periods=n)
        close = pd.Series(
            100 * np.cumprod(1 + rng.normal(0.0004 + i * 0.0002, 0.016, n)),
            index=idx)
        bars_map[code] = pd.DataFrame(
            {"open": close, "high": close * 1.01, "low": close * 0.99,
             "close": close, "volume": rng.integers(1e5, 5e5, n).astype(float)},
            index=idx)

    windows = [("2021-01-01", "2022-12-31"), ("2023-01-01", "2024-12-31")]
    grid = run_grid(bars_map, ["ma_cross", "rsi_reversion"], windows,
                    market="CN", min_bars=120)
    assert grid["count"] > 0, grid["failures"]
    assert {c["strategy"] for c in grid["cells"]} == {"ma_cross", "rsi_reversion"}

    summ = grid_summary(grid)
    assert summ["count"] == grid["count"]
    for dim in ("by_strategy", "by_code", "by_window"):
        assert summ[dim], dim
        for k, v in summ[dim].items():
            assert 0 <= v["win_rate_pct"] <= 100

    # 组合感知聚合：权重合成后重算
    eq = {k: v for k, v in (grid.get("_equity") or {}).items()}
    # 取同一窗口下的不同标的净值做组合
    sel = {k: v for k, v in eq.items() if k.endswith("2021-01-01~2022-12-31")}
    agg = portfolio_aggregate(sel)
    assert agg["n"] == len(sel) >= 2
    m = agg["metrics"]
    assert set(m) >= {"total_return_pct", "max_drawdown_pct", "sharpe"}
    # 组合最大回撤应不大于各成分最差回撤（分散化效应，用绝对值比较）
    worst_single = min(
        float((s / s.cummax() - 1).min()) for s in sel.values())
    assert m["max_drawdown_pct"] / 100.0 >= worst_single - 1e-6

    # 自定义权重归一
    agg2 = portfolio_aggregate(sel, weights={list(sel)[0]: 3, list(sel)[1]: 1})
    w = agg2["weights"]
    assert abs(sum(w.values()) - 1.0) < 1e-6, w

    print(f"batch_backtest self-check ok "
          f"(cells={grid['count']}, 组合 n={agg['n']}, "
          f"total={m['total_return_pct']}%, mdd={m['max_drawdown_pct']}%)")
