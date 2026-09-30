# -*- coding: utf-8 -*-
"""CFA 级分析模块（模块五 · 参考 FinceptTerminal CFA 分析）。

三类机构级分析能力（全部确定性、无新依赖、可单测）：
1. 估值模型：DDM（戈登增长）、PEG、格雷厄姆公式、EV/EBITDA 倍数；
2. 财务比率：盈利能力/偿债/运营/成长 4 类 16+ 指标；
3. 风险度量：VaR（历史法/参数法）、CVaR、最大回撤、波动率、下行风险。

`cfa_report(snapshot, bars)` 返回结构化 {valuation, ratios, risk, verdict}。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

log = logging.getLogger("stockai.core.quant.cfa")

# ---------------------------------------------------------------------------
# 估值模型
# ---------------------------------------------------------------------------
def ddm_gordon(dps: float, growth: float, required_return: float) -> float:
    """戈登增长模型：V = DPS*(1+g)/(r-g)。r<=g 返回 inf（模型失效）。"""
    if required_return <= growth:
        return float("inf")
    return dps * (1 + growth) / (required_return - growth)


def peg_ratio(pe: float, growth_pct: float) -> float:
    """PEG = PE / 盈利增长率(%)。growth<=0 时返回 inf（无成长支撑）。"""
    if pe <= 0 or growth_pct <= 0:
        return float("inf")
    return pe / growth_pct


def graham_value(eps: float, bvps: float) -> float:
    """格雷厄姆公式：V = sqrt(22.5 * EPS * BVPS)。"""
    return float(np.sqrt(max(22.5 * eps * bvps, 0.0)))


def ev_ebitda(ev: float, ebitda: float) -> float:
    if ebitda <= 0:
        return float("inf")
    return ev / ebitda


# ---------------------------------------------------------------------------
# 财务比率（4 类 16 项）
# ---------------------------------------------------------------------------
def calculate_ratios(fin: Dict[str, float]) -> Dict[str, float]:
    """输入财务快照，输出 16 项比率（缺失字段跳过）。"""
    g = lambda k, d=0.0: float(fin.get(k, d) or d)  # noqa: E731
    out: Dict[str, float] = {}
    rev, ni = g("revenue"), g("net_income")
    eq, ta, tl = g("equity"), g("total_assets"), g("total_liabilities")
    cur_a, cur_l = g("current_assets"), g("current_liabilities")
    ocf, capex = g("operating_cash_flow"), g("capex")
    # 盈利能力
    if rev:
        out["gross_margin"] = g("gross_profit") / rev
        out["net_margin"] = ni / rev
        out["roe"] = ni / eq if eq else float("nan")
        out["roa"] = ni / ta if ta else float("nan")
    # 偿债能力
    if eq:
        out["debt_equity"] = tl / eq if eq else float("nan")
    if cur_l:
        out["current_ratio"] = cur_a / cur_l
    if ta:
        out["asset_liability"] = tl / ta
    # 运营效率
    if rev and ta:
        out["asset_turnover"] = rev / ta
    if fin.get("inventory") and fin.get("cogs"):
        out["inventory_turnover"] = g("cogs") / g("inventory")
    if rev and fin.get("receivables"):
        out["receivables_turnover"] = rev / g("receivables")
    # 成长性
    if fin.get("revenue_prev"):
        out["revenue_growth"] = rev / g("revenue_prev") - 1
    if fin.get("net_income_prev"):
        out["profit_growth"] = ni / g("net_income_prev") - 1
    # 现金流
    if ni:
        out["cash_conversion"] = ocf / ni if ocf else float("nan")
    if capex and ocf:
        out["fcf_margin"] = (ocf - capex) / rev if rev else float("nan")
    return {k: float(v) for k, v in out.items()
            if not (isinstance(v, float) and np.isnan(v))}


# ---------------------------------------------------------------------------
# 风险度量
# ---------------------------------------------------------------------------
def risk_metrics(ret: pd.Series, confidence: float = 0.95,
                 risk_free: float = 0.02) -> Dict[str, float]:
    """基于收益序列的风险度量（VaR/CVaR/回撤/波动/下行风险）。"""
    ret = ret.dropna().astype(float)
    if len(ret) < 10:
        return {"error": "样本不足"}
    hist_var = float(-np.percentile(ret, (1 - confidence) * 100))
    cvar = float(-ret[ret <= -hist_var].mean()) if len(ret[ret <= -hist_var]) else 0.0
    ann_vol = float(ret.std() * np.sqrt(252))
    downside = ret[ret < 0]
    downside_risk = float(downside.std() * np.sqrt(252)) if len(downside) > 1 else 0.0
    eq = (1 + ret).cumprod()
    max_dd = float((eq / eq.cummax() - 1).min())
    ann_ret = float((1 + ret.mean()) ** 252 - 1)
    sharpe = float((ann_ret - risk_free) / ann_vol) if ann_vol > 0 else 0.0
    sortino = float((ann_ret - risk_free) / downside_risk) \
        if downside_risk > 0 else 0.0
    return {"var_hist": hist_var, "cvar": cvar, "annual_vol": ann_vol,
            "downside_risk": downside_risk, "max_drawdown": max_dd,
            "annual_return": ann_ret, "sharpe": sharpe, "sortino": sortino}


# ---------------------------------------------------------------------------
# 汇总报告
# ---------------------------------------------------------------------------
def cfa_report(fin: Dict[str, float], ret: pd.Series,
               extra: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    """CFA 级综合分析。extra 可传 dps/growth/required_return/pe/bvps/ev/ebitda。"""
    extra = extra or {}
    ratios = calculate_ratios(fin)
    risk = risk_metrics(ret)
    valuation: Dict[str, float] = {}
    if extra.get("dps") is not None:
        valuation["ddm"] = ddm_gordon(float(extra["dps"]),
                                      float(extra.get("growth", 0.03)),
                                      float(extra.get("required_return", 0.10)))
    if extra.get("pe") is not None:
        valuation["peg"] = peg_ratio(float(extra["pe"]),
                                     float(extra.get("growth_pct", 0)))
    if extra.get("eps") is not None and extra.get("bvps") is not None:
        valuation["graham"] = graham_value(float(extra["eps"]),
                                           float(extra["bvps"]))
    if extra.get("ev") is not None and extra.get("ebitda") is not None:
        valuation["ev_ebitda"] = ev_ebitda(float(extra["ev"]),
                                           float(extra["ebitda"]))
    roe = ratios.get("roe")
    margin = ratios.get("net_margin")
    verdict = []
    if roe is not None and roe < 0.05:
        verdict.append("ROE 偏低（<5%），资本回报承压")
    if margin is not None and margin < 0:
        verdict.append("净利润率为负，盈利能力堪忧")
    if risk.get("max_drawdown", 0) < -0.3:
        verdict.append("历史最大回撤超 30%，波动风险高")
    if "peg" in valuation and valuation["peg"] < 1:
        verdict.append("PEG<1，估值相对成长性偏低")
    return {"valuation": valuation, "ratios": ratios, "risk": risk,
            "verdict": verdict or ["基本面与风险指标未见显著异常"]}


if __name__ == "__main__":
    # 自检
    assert abs(ddm_gordon(1.0, 0.05, 0.10) - 21.0) < 1e-6
    assert peg_ratio(15, 10) == 1.5
    assert peg_ratio(15, 0) == float("inf")
    assert abs(graham_value(2, 10) - np.sqrt(450)) < 1e-6
    fin = {"revenue": 1000.0, "net_income": 120.0, "equity": 600.0,
           "total_assets": 1500.0, "total_liabilities": 900.0,
           "current_assets": 500.0, "current_liabilities": 300.0,
           "gross_profit": 400.0, "operating_cash_flow": 150.0,
           "revenue_prev": 850.0, "net_income_prev": 100.0}
    r = calculate_ratios(fin)
    assert abs(r["net_margin"] - 0.12) < 1e-9
    assert abs(r["roe"] - 0.20) < 1e-9
    assert abs(r["revenue_growth"] - (1000 / 850 - 1)) < 1e-9
    rng = np.random.default_rng(6)
    ret = pd.Series(rng.normal(0.0005, 0.02, 200))
    rm = risk_metrics(ret)
    assert 0 <= rm["var_hist"] < 1 and rm["max_drawdown"] <= 0
    full = cfa_report(fin, ret, {"dps": 0.8, "growth": 0.05,
                                  "required_return": 0.10, "pe": 18,
                                  "growth_pct": 12, "eps": 2.0, "bvps": 10.0})
    assert "ddm" in full["valuation"] and "peg" in full["valuation"]
    assert full["verdict"]
    print("cfa_analysis self-check ok")
