# -*- coding: utf-8 -*-
"""文本梯度策略优化（TradeGrad 工程实现）（2026-10 翻新 · 模块一）。

参考 TradeGrad：用文本梯度（textual gradient）迭代重写交易策略参数/源码，
由回测性能衍生的文本反馈引导。其评分标准刻意「反脆弱」——不以总收益为
目标，而以**年度回测窗口中最差 30% 的 CVaR** 为评分，防止搜索通过
「在某一年爆仓、其余年份暴涨」来骗取高分。

本模块提供确定性内核（可单测、可复现）：

- `window_returns()`：把日收益切分为年度窗口收益序列；
- `worst_cvar()`：取最差 30% 窗口，计算其条件在险值（尾部均值），越接近 0 越好；
- `score_candidate()`：跑一次回测 → 年度窗口 → 最差 30% CVaR → 综合分；
- `text_gradient()`：由历史迭代记录生成**文本梯度**（改进建议文本），
  确定性模板生成；若提供 LLM proposer 则交给模型润色（可选）；
- `iterate()`：完整的「采样参考集 → 生成梯度 → 选择基础程序 → 修订 → 评分」
  循环，全过程写入 SQLite 留痕（策略迭代可追溯、可复盘）。

评分口径：score = 最差30%窗口CVaR（越高越好，负值越小越差），
并同时报告总收益/最大回撤供人工复核——避免「只优化尾部、整体不赚钱」。
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
from contextlib import closing
from typing import Any, Callable, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

import numpy as np
import pandas as pd

from core.config import DATA_DIR
from core import db_util

_ITER_DB = DATA_DIR / "text_grad_iterations.db"
_SCHEMA = """
CREATE TABLE IF NOT EXISTS text_grad_iterations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    strategy TEXT NOT NULL,
    iteration INTEGER NOT NULL,
    params TEXT NOT NULL,
    score REAL NOT NULL,
    worst_cvar REAL NOT NULL,
    total_return REAL,
    max_drawdown REAL,
    gradient TEXT,
    parent_id INTEGER
);
CREATE INDEX IF NOT EXISTS ix_tg_strategy ON text_grad_iterations(strategy, ts);
"""

# 参数网格（用于生成候选邻居：确定性、可复现）
_PARAM_NEIGHBORS: Dict[str, List[Any]] = {
    "fast": [3, 5, 8, 10, 13],
    "slow": [20, 30, 45, 60],
    "rsi_period": [6, 10, 14, 21],
    "buy_thr": [20, 25, 30, 35],
    "sell_thr": [65, 70, 75, 80],
    "macd_fast": [8, 12, 16],
    "macd_slow": [20, 26, 34],
    "macd_signal": [6, 9, 12],
}


def _conn() -> sqlite3.Connection:
    _ITER_DB.parent.mkdir(parents=True, exist_ok=True)
    con = db_util.connect(_ITER_DB, timeout=10, retries=3)
    con.executescript(_SCHEMA)
    return con


# ---------------------------------------------------------------------------
# 评分内核
# ---------------------------------------------------------------------------

def window_returns(daily_returns: pd.Series, freq: str = "YE") -> List[float]:
    """把日收益按年度（默认）切分为窗口收益序列。"""
    if daily_returns is None or len(daily_returns) == 0:
        return []
    s = pd.Series(daily_returns).dropna()
    if len(s) == 0:
        return []
    if not isinstance(s.index, pd.DatetimeIndex):
        return [float((1 + s).prod() - 1.0)]
    # pandas 3：年度周期别名为 "Y"（"YE" 是 offset 别名，to_period 不接受）
    alias = {"YE": "Y", "YE-DEC": "Y", "A": "Y", "A-DEC": "Y",
             "ME": "M", "M": "M", "QE": "Q", "Q": "Q"}.get(freq, freq)
    out: List[float] = []
    for _k, grp in s.groupby(s.index.to_period(alias)):
        out.append(float((1 + grp).prod() - 1.0))
    return out


def worst_cvar(window_scores: List[float], worst_ratio: float = 0.3) -> float:
    """最差 worst_ratio 比例窗口的条件在险值（尾部均值）。

    返回值为负表示最差年份平均亏损幅度；越接近 0（或为正）越好。
    """
    if not window_scores:
        return 0.0
    arr = np.sort(np.asarray(window_scores, dtype=float))
    k = max(1, int(np.ceil(len(arr) * float(worst_ratio))))
    tail = arr[:k]
    return float(tail.mean())


def score_candidate(bars: pd.DataFrame, market: str, strategy: str,
                    params: Optional[dict] = None, config=None,
                    worst_ratio: float = 0.3) -> Dict[str, Any]:
    """对一组参数评分。返回 {score, worst_cvar, windows, total_return, max_drawdown}。

    score = worst_cvar（最差 30% 年度窗口均值），越高越好。
    """
    from core.quant.backtest import run_backtest

    try:
        res = run_backtest(bars, market, strategy, params or None, config)
    except Exception as e:  # noqa: BLE001
        return {"error": f"回测失败：{e}", "score": -1e9,
                "worst_cvar": -1e9, "windows": []}
    eq = res.equity["strategy"]
    rets = eq.pct_change().dropna()
    wins = window_returns(rets)
    cvar = worst_cvar(wins, worst_ratio)
    m = res.metrics
    return {
        "score": cvar,
        "worst_cvar": cvar,
        "windows": [round(w, 4) for w in wins],
        "total_return": m.get("total_return_pct"),
        "max_drawdown": m.get("max_drawdown_pct"),
        "trade_count": m.get("trade_count"),
    }


# ---------------------------------------------------------------------------
# 文本梯度
# ---------------------------------------------------------------------------

def text_gradient(history: List[Dict[str, Any]],
                  current: Dict[str, Any]) -> str:
    """由迭代历史生成文本梯度（改进建议）。

    确定性模板：① 若尾部亏损大 → 建议收紧入场/加保护；
    ② 若交易次数过多 → 建议降低换手（成本侵蚀尾部）；
    ③ 若窗口数不足 → 提示样本不足，结论不可靠；
    ④ 若有更优父代 → 建议回退到父代邻域继续搜索。
    """
    cvar = float(current.get("worst_cvar", 0.0))
    best = max(history, key=lambda h: h.get("worst_cvar", -1e9)) if history else None
    lines: List[str] = []
    if not history:
        lines.append("首轮：尚无历史参考。建议先覆盖参数网格的典型取值"
                     "（如均线 5/20、RSI 14/30-70），建立基线。")
    # 样本量检查与历史无关，必须始终执行（样本不足 → 结论标注「未检出」）
    if len(current.get("windows") or []) < 3:
        lines.append("年度窗口不足 3 个，尾部统计不可靠 → "
                     "结论应标注「未检出/样本不足」，勿据此上线。")
    if cvar < -0.15:
        lines.append("最差 30% 年度窗口平均亏损超 15% → 收紧入场条件、"
                     "缩短持仓周期或引入趋势过滤，优先修复尾部而非追逐总收益。")
    elif cvar < 0:
        lines.append("最差窗口仍为负但幅度可控 → 在保持当前结构的前提下"
                     "微调阈值，观察尾部是否继续收敛。")
    else:
        lines.append("最差窗口已非负 → 尝试小幅放大仓位/放宽阈值，"
                     "检验收益弹性是否以尾部恶化为代价。")
    tc = current.get("trade_count") or 0
    if tc and tc > 40:
        lines.append(f"交易次数 {tc} 偏高，成本与滑点在尾部年份被放大 → "
                     f"建议降低换手（拉长均线周期或提高信号阈值）。")
    if best is not None and best.get("worst_cvar", -1e9) > cvar:
        lines.append(f"历史最优（CVaR={best.get('worst_cvar'):.3f}，"
                     f"参数={best.get('params')}）优于当前 → "
                     f"回退到该邻域继续搜索。")
    return " ".join(lines)


def neighbors(params: dict) -> List[dict]:
    """生成参数邻居（网格上/下一步），确定性、可复现。"""
    out: List[dict] = []
    for key, val in params.items():
        grid = _PARAM_NEIGHBORS.get(key)
        if not grid or val not in grid:
            continue
        i = grid.index(val)
        for j in (i - 1, i + 1):
            if 0 <= j < len(grid):
                cand = dict(params)
                cand[key] = grid[j]
                out.append(cand)
    return out


# ---------------------------------------------------------------------------
# 迭代优化
# ---------------------------------------------------------------------------

def iterate(bars: pd.DataFrame, market: str, strategy: str,
            base_params: Optional[dict] = None, n_iter: int = 3,
            worst_ratio: float = 0.3, config=None,
            proposer: Optional[Callable[[List[Dict[str, Any]], Dict[str, Any]], str]] = None,
            persist: bool = True) -> Dict[str, Any]:
    """文本梯度迭代优化。返回 {best, history, trace_id, iterations}。

    proposer 可选：LLM 生成梯度文本（默认用确定性模板 text_gradient）。
    """
    from core.quant.backtest import DEFAULT_PARAMS

    params = dict(DEFAULT_PARAMS.get(strategy, {}))
    params.update(base_params or {})
    history: List[Dict[str, Any]] = []
    parent_id: Optional[int] = None

    cur = score_candidate(bars, market, strategy, params, config, worst_ratio)
    cur.update({"params": params, "iteration": 0})
    best = dict(cur)

    for it in range(1, int(n_iter) + 1):
        grad = proposer(history, cur) if proposer else text_gradient(history, cur)
        cands = neighbors(params) or []
        scored: List[Dict[str, Any]] = []
        for cand in cands:
            s = score_candidate(bars, market, strategy, cand, config, worst_ratio)
            if "error" in s:
                continue
            s.update({"params": cand, "iteration": it})
            scored.append(s)
        if scored:
            # 以最差 30% CVaR 为准选优（不是总收益）
            nxt = max(scored, key=lambda s: s["worst_cvar"])
            if nxt["worst_cvar"] > cur["worst_cvar"]:
                params = nxt["params"]
                cur = nxt
        cur["gradient"] = grad
        history.append(dict(cur))
        if cur["worst_cvar"] > best["worst_cvar"]:
            best = dict(cur)
        if persist:
            parent_id = _log_iteration(strategy, it, cur.get("params", {}),
                                       cur.get("worst_cvar", 0.0), cur,
                                       grad, parent_id)
        cur = dict(cur)

    return {
        "best": {k: best.get(k) for k in
                 ("params", "worst_cvar", "total_return", "max_drawdown",
                  "trade_count", "windows")},
        "best_score": best.get("worst_cvar"),
        "history": history,
        "iterations": len(history),
        "scoring": f"最差 {int(worst_ratio * 100)}% 年度窗口 CVaR",
        "note": "评分以尾部风险为准，不以总收益为准；样本不足时结论标注「未检出」。",
    }


def _log_iteration(strategy: str, iteration: int, params: dict,
                   cvar: float, metrics: dict, gradient: str,
                   parent_id: Optional[int]) -> int:
    with closing(_conn()) as con:
        cur = con.execute(
            "INSERT INTO text_grad_iterations"
            "(ts, strategy, iteration, params, score, worst_cvar,"
            " total_return, max_drawdown, gradient, parent_id)"
            " VALUES(?,?,?,?,?,?,?,?,?,?)",
            (time.time(), strategy, iteration,
             json.dumps(params, ensure_ascii=False), float(cvar), float(cvar),
             metrics.get("total_return"), metrics.get("max_drawdown"),
             gradient[:2000], parent_id))
        con.commit()
        return int(cur.lastrowid)


def iteration_history(strategy: str, limit: int = 20) -> List[Dict[str, Any]]:
    """读取迭代留痕（新→旧），供 UI 策略迭代复盘。"""
    with closing(_conn()) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT * FROM text_grad_iterations WHERE strategy=?"
            " ORDER BY id DESC LIMIT ?", (strategy, int(limit))).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["params"] = json.loads(d["params"] or "{}")
        out.append(d)
    return out


if __name__ == "__main__":
    rng = np.random.default_rng(7)
    n = 900  # 约 3.5 年，保证 ≥3 个年度窗口
    idx = pd.bdate_range("2022-01-01", periods=n)
    # 分段构造：让不同年份表现明显不同（检验尾部评分）
    seg = [rng.normal(0.0012, 0.012, 250), rng.normal(-0.0008, 0.020, 250),
           rng.normal(0.0006, 0.014, 250), rng.normal(0.0010, 0.010, 150)]
    close = pd.Series(100 * np.cumprod(1 + np.concatenate(seg)), index=idx)
    bars = pd.DataFrame({"open": close, "high": close * 1.01,
                         "low": close * 0.99, "close": close,
                         "volume": rng.integers(1e5, 5e5, n).astype(float)},
                        index=idx)

    # 1) 窗口划分与尾部 CVaR
    rets = close.pct_change().dropna()
    wins = window_returns(rets)
    assert len(wins) >= 3, wins
    cv = worst_cvar(wins, 0.3)
    assert isinstance(cv, float)

    # 2) 评分：给了真实回测
    s = score_candidate(bars, "CN", "ma_cross", {"fast": 5, "slow": 20})
    assert "worst_cvar" in s and "windows" in s

    # 3) 迭代：跑 3 轮，历史可追溯，best 不劣于首轮
    res = iterate(bars, "CN", "ma_cross", {"fast": 5, "slow": 20}, n_iter=3)
    assert res["iterations"] == 3
    assert res["best_score"] >= res["history"][0]["worst_cvar"] - 1e-9
    assert all(h.get("gradient") for h in res["history"])

    # 4) 邻居生成确定性
    nb = neighbors({"fast": 5, "slow": 20})
    assert {"fast": 3, "slow": 20} in nb and {"fast": 8, "slow": 20} in nb

    # 5) 留痕可读回
    hist = iteration_history("ma_cross", limit=5)
    assert len(hist) >= 1 and "params" in hist[0]

    print(f"text_grad self-check ok (windows={[round(w, 3) for w in wins]}, "
          f"cvar={cv:.3f}, best={res['best_score']:.3f}, "
          f"best_params={res['best']['params']})")
