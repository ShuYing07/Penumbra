# -*- coding: utf-8 -*-
"""回测严谨性审计：前视偏差扫描 + Walk-Forward 样本内外验证。

前视偏差扫描（参考 Freqtrade lookahead-analysis 思路，不读策略代码）：
对一个信号在它产生时刻截断未来数据后重新计算信号——若截断后的信号与
完整回测中的信号一致，说明该信号只使用了当时已知的数据；不一致则标记
为可疑/未通过（可能使用了未来数据，或实现依赖了未来窗口）。

Walk-Forward：数据按时间切分为样本内（训练期，默认前 60%）与样本外
（验证期，后 40%），分别报告绩效，用于识别过拟合。

全部输出为客观评估结果，不构成投资建议。
"""
from __future__ import annotations

import logging
from typing import Optional

import pandas as pd

from core.quant.backtest import STRATEGIES, run_backtest

log = logging.getLogger("stockai.quant.audit")


def scan_lookahead(df: pd.DataFrame, strategy: str, params: Optional[dict] = None,
                   max_checks: int = 50) -> dict:
    """对策略信号做前视偏差扫描。返回 {verdict, checked, mismatches, ratio, detail}。"""
    sig_fn = STRATEGIES.get(strategy)
    if sig_fn is None:
        return {"verdict": "na", "reason": f"{strategy} 无信号函数（如 buy_hold），不适用"}
    try:
        full = sig_fn(df, params or {}).astype(int)
    except Exception as e:  # noqa: BLE001
        return {"verdict": "error", "reason": f"信号计算失败：{e}"}

    idx = full.index[full != 0]
    if len(idx) == 0:
        return {"verdict": "na", "reason": "全样本无信号，无前视偏差可检查"}

    step = max(1, len(idx) // max_checks)
    sample = idx[::step][:max_checks]
    mism: list[dict] = []
    for t in sample:
        pos = df.index.get_loc(t)
        sub = df.iloc[: pos + 1]  # 截至 t（含 t）的数据——未来被截断
        try:
            sig_trunc = sig_fn(sub, params or {}).astype(int)
        except Exception:  # noqa: BLE001
            continue
        v_full = int(full.loc[t])
        v_trunc = int(sig_trunc.iloc[-1])
        if v_full != v_trunc:
            mism.append({"date": str(t), "sig_full": v_full, "sig_trunc": v_trunc})

    checked = len(sample)
    if checked == 0:
        return {"verdict": "na", "reason": "信号样本为空"}
    ratio = round(len(mism) / checked, 3)
    verdict = "pass" if ratio == 0 else ("suspect" if ratio <= 0.2 else "fail")
    return {
        "verdict": verdict,
        "checked": checked,
        "mismatches": len(mism),
        "ratio": ratio,
        "detail": mism[:10],
        "note": (
            "通过：信号在截断未来数据后保持一致；"
            "可疑：少量信号点出现偏移（≤20%）；"
            "未通过：>20% 信号点偏移，疑似使用未来数据"),
    }


def walk_forward(df: pd.DataFrame, market: str, strategy: str,
                 params: Optional[dict] = None, config=None,
                 in_ratio: float = 0.6) -> dict:
    """Walk-Forward 验证：样本内（前 in_ratio）/样本外（后 1-in_ratio）分别回测。"""
    n = len(df)
    if n < 120:
        return {"error": f"数据不足（{n} 根），Walk-Forward 至少需 120 根"}
    cut = int(n * in_ratio)
    df_in, df_out = df.iloc[:cut], df.iloc[cut:]
    try:
        res_in = run_backtest(df_in, market, strategy, params or None, config)
        res_out = run_backtest(df_out, market, strategy, params or None, config)
        res_full = run_backtest(df, market, strategy, params or None, config)
    except Exception as e:  # noqa: BLE001
        return {"error": f"回测失败：{e}"}
    return {
        "split_date": str(df.index[cut]),
        "in_bars": cut,
        "out_bars": n - cut,
        "in": res_in.metrics,
        "out": res_out.metrics,
        "full": res_full.metrics,
    }


def run_audit(df: pd.DataFrame, market: str, strategy: str,
              params: Optional[dict] = None, config=None,
              in_ratio: float = 0.6) -> dict:
    """一站式回测审计：前视偏差 + Walk-Forward + 稳健性指标（GT-Score 等）。"""
    look = scan_lookahead(df, strategy, params)
    wf = walk_forward(df, market, strategy, params, config, in_ratio)
    robust = {}
    try:
        res = run_backtest(df, market, strategy, params or None, config)
        from core.quant.backtest import permutation_test
        _rets = res.equity["strategy"].pct_change().fillna(0.0)
        _positions = (_rets.abs() > 1e-9).astype(float).values  # 净值变化非0 → 持仓
        perm = permutation_test(_rets, _positions)
        from core.quant.robust_metrics import robust_report
        robust = robust_report(res.metrics, perm["p_value"],
                               res.equity["strategy"].pct_change().dropna(),
                               res.equity, res.rounds)
    except Exception as e:  # noqa: BLE001
        robust = {"error": f"稳健性指标计算失败：{e}"}
    return {"strategy": strategy, "lookahead": look, "walk_forward": wf,
            "robust": robust}
