# -*- coding: utf-8 -*-
"""参数网格搜索与稳健性评估（纯 pandas，复用 core.quant.backtest，不联网不写库）。

防过拟合三道关：
1. 目标函数排名（sharpe 默认 / 总收益 / calmar）；
2. 绩效平原：最优点的网格邻居表现是否同样好（孤立尖峰=过拟合警示）；
3. Walk-forward：前 60% 区间选参数，后 40% 区间看该参数的排名分位。
"""
from __future__ import annotations

import itertools
from typing import Callable

import pandas as pd

from core.quant.backtest import (DEFAULT_PARAMS, STRATEGY_META, BacktestConfig,
                                  BacktestResult, run_backtest)

MAX_COMBOS = 500

# 各策略的默认寻优网格（值取常用区间，步长兼顾组合数）
DEFAULT_GRIDS: dict[str, dict[str, list]] = {
    "rsi_reversion": {
        "rsi_period": [7, 14, 21],
        "buy_thr": [20, 25, 30, 35],
        "sell_thr": [65, 70, 75, 80],
    },
    "ma_cross": {
        "fast": [3, 5, 10],
        "slow": [20, 30, 60],
    },
    "macd_cross": {
        "macd_fast": [8, 12, 16],
        "macd_slow": [26, 34],
        "macd_signal": [7, 9, 12],
    },
}


# ---------------------------------------------------------------------------
# 目标函数
# ---------------------------------------------------------------------------
def _obj_sharpe(m: dict) -> float:
    return float(m.get("sharpe", 0.0))


def _obj_return(m: dict) -> float:
    return float(m.get("total_return_pct", 0.0))


def _obj_calmar(m: dict) -> float:
    ann = float(m.get("annual_return_pct", 0.0))
    dd = abs(float(m.get("max_drawdown_pct", 0.0)))
    return ann / dd if dd >= 0.01 else ann * 100.0   # 回撤近 0 时给大值避免除零


OBJECTIVES: dict[str, Callable[[dict], float]] = {
    "sharpe": _obj_sharpe,
    "return": _obj_return,
    "calmar": _obj_calmar,
}

OBJECTIVE_LABELS = {"sharpe": "夏普比率", "return": "总收益率", "calmar": "Calmar(年化/最大回撤)"}


# ---------------------------------------------------------------------------
# 网格
# ---------------------------------------------------------------------------
def expand_grid(spec: dict[str, list]) -> list[dict]:
    """参数网格笛卡尔积。空网格或组合数超 MAX_COMBOS 抛 ValueError。"""
    spec = {k: list(v) for k, v in spec.items() if list(v)}
    if not spec:
        raise ValueError("参数网格为空")
    for k, v in spec.items():
        if not v:
            raise ValueError(f"参数 {k} 的候选值为空")
    keys = list(spec.keys())
    combos = [dict(zip(keys, vals)) for vals in itertools.product(*spec.values())]
    if len(combos) > MAX_COMBOS:
        raise ValueError(
            f"参数组合数 {len(combos)} 超过上限 {MAX_COMBOS}，请缩小网格（减少候选值）")
    return combos


def _key(params: dict) -> tuple:
    return tuple(sorted(params.items()))


def run_grid(df: pd.DataFrame, market: str, strategy: str,
             spec: dict[str, list], config: BacktestConfig | None = None,
             objective: str = "sharpe",
             progress_cb: Callable[[int, int], None] | None = None) -> list[dict]:
    """对网格内每组参数跑一次回测，返回按目标值降序的结果列表。

    每项：{params, objective, objective_name, traded(是否发生过交易), metrics}
    0 交易组合（trade_count=0）排末尾（同组内再按目标值）。
    """
    if strategy not in STRATEGY_META or strategy == "buy_hold":
        raise ValueError(f"参数寻优仅支持带参数策略：rsi_reversion/ma_cross/macd_cross（收到 {strategy}）")
    if objective not in OBJECTIVES:
        raise ValueError(f"未知目标函数 {objective}（可选 {list(OBJECTIVES)}）")
    combos = expand_grid(spec)
    obj_fn = OBJECTIVES[objective]
    out: list[dict] = []
    for i, params in enumerate(combos, 1):
        if progress_cb:
            progress_cb(i, len(combos))
        res: BacktestResult = run_backtest(df, market, strategy, params=params, config=config)
        m = res.metrics
        out.append({
            "params": params,
            "objective_name": objective,
            "objective": round(obj_fn(m), 4),
            "traded": m.get("trade_count", 0) > 0,
            "metrics": m,
        })
    out.sort(key=lambda r: (r["traded"], r["objective"]), reverse=True)
    return out


# ---------------------------------------------------------------------------
# 绩效平原评估
# ---------------------------------------------------------------------------
def grid_neighbors(best: dict, spec: dict[str, list]) -> list[dict]:
    """最优点在网格上的直接邻居：每个参数维度取相邻一格、其余维度固定。"""
    out: list[dict] = []
    for k, values in spec.items():
        if k not in best or len(values) < 2:
            continue
        cur = best[k]
        try:
            idx = list(values).index(cur)
        except ValueError:
            continue
        for j in (idx - 1, idx + 1):
            if 0 <= j < len(values):
                nb = dict(best)
                nb[k] = values[j]
                out.append(nb)
    return out


# 平原容忍带：邻居目标值与最优差距 ≤ tol 视为"表现同质"（按指标语义给尺度）
PLATEAU_TOL = {"sharpe": 0.1, "return": 5.0, "calmar": 0.2}


def assess_plateau(results: list[dict], spec: dict[str, list],
                   tol: float | None = None) -> dict:
    """评估最优点是否处于绩效平原（邻居同样好=稳健，孤立尖峰=过拟合风险）。

    robust = 邻居中"目标值与最优差距在容忍带内"的比例（0~1，越高越平原）。
    不用极差归一：平原场景极差本身就小，极差归一会把小差异放大成尖峰。
    """
    traded = [r for r in results if r["traded"]]
    pool = traded or results
    if not pool:
        return {"rating": "无可行组合", "robust": None, "neighbors": []}
    best = pool[0]
    if tol is None:
        tol = PLATEAU_TOL.get(best.get("objective_name", "sharpe"), 0.1)
    by_key = {_key(r["params"]): r for r in results}
    nbr_rows = [by_key[_key(nb)] for nb in grid_neighbors(best["params"], spec)
                if _key(nb) in by_key]
    if not nbr_rows:
        return {"rating": "网格过小，无邻居可判", "robust": None,
                "neighbors": [], "best": best}
    within = [1 if abs(best["objective"] - n["objective"]) <= tol else 0 for n in nbr_rows]
    robust = round(sum(within) / len(within), 3)
    if len(nbr_rows) < 2:
        rating = "邻居不足，结论参考性弱"
    elif robust >= 0.7:
        rating = "稳健平原（邻居参数表现接近，过拟合风险低）"
    elif robust >= 0.4:
        rating = "一般（半平原，参数敏感性中等）"
    else:
        rating = "孤立尖峰（邻居明显更差，过拟合风险高，慎用）"
    return {"rating": rating, "robust": robust, "tol": tol,
            "best": best,
            "neighbors": [{"params": n["params"], "objective": n["objective"],
                           "traded": n["traded"],
                           "within_tol": abs(best["objective"] - n["objective"]) <= tol}
                          for n in nbr_rows]}


# ---------------------------------------------------------------------------
# Walk-forward
# ---------------------------------------------------------------------------
def walk_forward(df: pd.DataFrame, market: str, strategy: str,
                 spec: dict[str, list], config: BacktestConfig | None = None,
                 split: float = 0.6, objective: str = "sharpe") -> dict:
    """样本内(前 split)选参数 → 样本外验证排名分位。"""
    if not 0.2 <= split <= 0.8:
        raise ValueError("split 须在 0.2~0.8 之间")
    n = len(df)
    cut = df.index[int(n * split)]
    cut_str = cut.strftime("%Y-%m-%d")
    idx = df.index
    oos_start = idx[min(int(n * split) + 1, n - 1)].strftime("%Y-%m-%d")

    is_cfg = _clone_cfg(config, market, end=cut_str)
    oos_cfg = _clone_cfg(config, market, start=oos_start)

    is_results = run_grid(df, market, strategy, spec, is_cfg, objective)
    oos_results = run_grid(df, market, strategy, spec, oos_cfg, objective)
    is_best = (next((r for r in is_results if r["traded"]), None) or is_results[0])

    by_key = {_key(r["params"]): r for r in oos_results}
    chosen = by_key.get(_key(is_best["params"]))
    if chosen is None:
        raise RuntimeError("IS 最优参数在 OOS 网格中缺失（不应发生）")

    ranked = sorted(oos_results, key=lambda r: (r["traded"], r["objective"]))
    rank_from_bottom = ranked.index(chosen)               # 0=最差
    percentile = round(rank_from_bottom / max(len(ranked) - 1, 1), 2)  # 1=事后最优
    if percentile >= 0.6:
        wf_rating = "跨期稳健（OOS 排名分位≥0.6）"
    elif percentile >= 0.4:
        wf_rating = "跨期一般"
    else:
        wf_rating = "跨期失效警示（IS 最优在 OOS 排名垫底，疑似过拟合）"

    return {
        "split_date": cut_str,
        "is_bars": int((df.index <= cut).sum()),
        "oos_bars": int((df.index > cut).sum()),
        "is_best_params": is_best["params"],
        "is_objective": is_best["objective"],
        "is_metrics": is_best["metrics"],
        "oos_objective_of_is_best": chosen["objective"],
        "oos_metrics_of_is_best": chosen["metrics"],
        "oos_ex_post_best": {"params": oos_results[0]["params"],
                             "objective": oos_results[0]["objective"]},
        "oos_percentile": percentile,
        "rating": wf_rating,
    }


def _clone_cfg(config: BacktestConfig | None, market: str,
               start: str | None = None, end: str | None = None) -> BacktestConfig:
    base = config or BacktestConfig(market=market)
    return BacktestConfig(ticker=base.ticker, market=base.market,
                          init_capital=base.init_capital,
                          position_pct=base.position_pct,
                          start=start if start is not None else base.start,
                          end=end if end is not None else base.end,
                          fee=base.fee)


# ---------------------------------------------------------------------------
# 总入口
# ---------------------------------------------------------------------------
def optimize(df: pd.DataFrame, market: str, strategy: str,
             spec: dict[str, list] | None = None,
             config: BacktestConfig | None = None,
             objective: str = "sharpe", split: float = 0.6,
             progress_cb: Callable[[str, int, int], None] | None = None) -> dict:
    """一次完整寻优：网格排名 + 平原评估 + walk-forward。"""
    spec = spec or DEFAULT_GRIDS.get(strategy)
    if not spec:
        raise ValueError(f"策略 {strategy} 无内置默认网格，请显式提供参数候选")

    def grid_cb(i, total):
        if progress_cb:
            progress_cb("grid", i, total)

    results = run_grid(df, market, strategy, spec, config, objective, grid_cb)
    if progress_cb:
        progress_cb("plateau", 1, 1)
    plateau = assess_plateau(results, spec)
    if progress_cb:
        progress_cb("walkforward", 1, 1)
    wf = walk_forward(df, market, strategy, spec, config, split, objective)
    return {
        "strategy": strategy,
        "objective": objective,
        "objective_label": OBJECTIVE_LABELS[objective],
        "n_combos": len(results),
        "results": results,
        "best": results[0],
        "plateau": plateau,
        "walk_forward": wf,
    }
