# -*- coding: utf-8 -*-
"""回测稳健性指标（模块三·策略评估升级）。

对齐 GT-Score（绩效+统计显著性+一致性+下行风险复合目标）与
Sharpe 稳定性比率、多空统计、持仓统计（天软择时评价风格）。
全部为客观统计输出，不构成投资建议。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

TRADING_DAYS = 252


def _clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(x)))


def sharpe_stability(daily_returns, window: int = 63) -> float:
    """Sharpe 稳定性比率：滚动 Sharpe 的变异系数倒数（0~1，越高越稳定）。

    口径：日收益滚动窗口计算 Sharpe → 序列均值/标准差 → stability = 1/(1+cv)。
    均值≤0（策略长期亏损）返回 0。
    """
    rets = pd.Series(np.asarray(daily_returns, dtype=float)).dropna()
    if len(rets) < window * 2:
        return 0.0
    roll = rets.rolling(window).agg(lambda x: (x.mean() / x.std() * np.sqrt(TRADING_DAYS)
                                               if x.std() > 1e-12 else 0.0)).dropna()
    if len(roll) < 2 or roll.mean() <= 0:
        return 0.0
    cv = float(roll.std() / max(abs(roll.mean()), 1e-9))
    return round(1.0 / (1.0 + cv), 3)


def long_short_stats(rounds: list[dict]) -> dict:
    """多空统计：回合次数/平均收益率/胜率/极端情况。

    当前引擎为确定性做多规则（t+1 开盘买入 → 信号反转卖出），
    输出做多回合的完整统计与极端尾部。
    """
    pnls = np.asarray([float(r["pnl"]) for r in rounds], dtype=float)
    n = int(len(pnls))
    if n == 0:
        return {"n_rounds": 0, "avg_return_pct": 0.0, "win_rate_pct": 0.0,
                "max_win_pct": 0.0, "max_loss_pct": 0.0, "extreme_rounds": 0,
                "note": "无已平仓回合"}
    wins = pnls[pnls > 0]
    losses = pnls[pnls <= 0]
    mean = float(pnls.mean())
    std = float(pnls.std())
    extreme = int((np.abs(pnls - mean) > 2 * std).sum()) if std > 1e-12 else 0
    return {
        "n_rounds": n,
        "avg_return_pct": round(mean, 2),
        "win_rate_pct": round(len(wins) / n * 100, 2),
        "max_win_pct": round(float(pnls.max()), 2),
        "max_loss_pct": round(float(pnls.min()), 2),
        "extreme_rounds": extreme,
        "side": "long-only（确定性做多规则）",
        "note": "极端回合：|收益-均值|>2σ 的回合数",
    }


def holding_stats(equity: pd.DataFrame, trapped_dd: float = 5.0,
                  gap_bench_pct: float = 3.0) -> dict:
    """持仓统计（套牢 / 踏空）。

    口径（近似，确定性规则引擎）：
    - 持仓日 = strategy 净值日收益非 0（满仓做多假设）；
    - 套牢 = 净值自峰值回撤超过 trapped_dd% 的天数占比；
    - 踏空 = 空仓日基准正收益合计超过 gap_bench_pct% 的次数（按连续空仓段累计）。
    """
    strat = equity["strategy"].astype(float)
    bench = equity["benchmark"].astype(float)
    rets = strat.pct_change().fillna(0.0)
    in_pos = rets.abs() > 1e-9

    cummax = strat.cummax()
    dd = strat / cummax - 1.0
    trapped_days = int((dd < -trapped_dd / 100).sum())
    total_days = int(len(strat))
    trapped_ratio = round(trapped_days / total_days * 100, 2) if total_days else 0.0

    bench_ret = bench.pct_change().fillna(0.0)
    gap_segments: list[float] = []
    acc = 0.0
    in_gap = False
    for pos, br in zip(in_pos, bench_ret):
        if not pos:
            acc += float(br)
            in_gap = True
        else:
            if in_gap and acc * 100 >= gap_bench_pct:
                gap_segments.append(acc * 100)
            acc = 0.0
            in_gap = False
    if in_gap and acc * 100 >= gap_bench_pct:
        gap_segments.append(acc * 100)

    return {
        "total_days": total_days,
        "position_days": int(in_pos.sum()),
        "flat_days": int((~in_pos).sum()),
        "trapped_days": trapped_days,
        "trapped_ratio_pct": trapped_ratio,          # 套牢（浮亏>阈值）天数占比
        "trapped_threshold_pct": trapped_dd,
        "missed_segments": len(gap_segments),         # 踏空段数（空仓期间基准涨超阈值）
        "missed_bench_pct": round(sum(gap_segments), 2),
        "gap_threshold_pct": gap_bench_pct,
    }


def gt_score(metrics: dict, p_value: float, daily_returns,
             w_perf: float = 0.35, w_sig: float = 0.30,
             w_cons: float = 0.25, w_dd: float = 0.10) -> dict:
    """GT-Score：复合目标函数（0~100）。

    四因子：绩效（年化收益，-50%~+50% 映射 0~1）、统计显著性（1-p）、
    一致性（Sharpe 稳定性 0~1）、下行风险惩罚（最大回撤 0~30% 映射 0~1）。
    """
    annual = _clip(float(metrics.get("annual_return_pct", 0.0)), -50, 50)
    perf = (annual + 50) / 100.0
    sig = _clip(1.0 - float(p_value), 0, 1)
    cons = float(sharpe_stability(daily_returns))
    dd_pen = _clip(-float(metrics.get("max_drawdown_pct", 0.0)), 0, 30) / 30.0
    raw = w_perf * perf + w_sig * sig + w_cons * cons - w_dd * dd_pen
    score = _clip(raw * 100, 0, 100)
    return {
        "gt_score": round(score, 2),
        "perf_term": round(w_perf * perf * 100, 2),
        "significance_term": round(w_sig * sig * 100, 2),
        "consistency_term": round(w_cons * cons * 100, 2),
        "downside_penalty": round(w_dd * dd_pen * 100, 2),
        "p_value": round(float(p_value), 4),
        "weights": {"perf": w_perf, "sig": w_sig, "cons": w_cons, "dd": w_dd},
    }


def robust_report(metrics: dict, p_value: float, daily_returns,
                  equity: pd.DataFrame, rounds: list[dict]) -> dict:
    """一站式稳健性报告（供回测审计面板展示）。"""
    return {
        "gt_score": gt_score(metrics, p_value, daily_returns),
        "sharpe_stability": sharpe_stability(daily_returns),
        "long_short": long_short_stats(rounds),
        "holding": holding_stats(equity),
    }
