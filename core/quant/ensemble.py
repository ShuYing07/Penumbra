# -*- coding: utf-8 -*-
"""程序量化综合分：融合 多因子(factors) + ML信号(ml) + 市场状态(regime) 为单一结论。

设计：
- factors.composite：技术/估值多因子综合分（0~100）
- ml.up_prob：随机森林未来5日上涨概率（0~1 → 0~100）
- regime：牛/熊/震荡，对综合分做轻度风险调节
- 融合权重：多因子 0.55（稳健、覆盖广）、ML 0.45（学习未来方向）；
  ML 不可用时退化为纯多因子。最终按 regime 做轻微压分（熊市更谨慎）。
- 输出统一 verdict(强烈看多/看多/中性/看空/强烈看空) + 依据，供风控层作确定性参考。
"""
from __future__ import annotations


def quantitative_score(factors: dict | None, ml: dict | None,
                       regime: dict | None) -> dict:
    fac = factors or {}
    ml = ml or {}
    regime = regime or {}

    comp = fac.get("composite")
    up_prob = ml.get("up_prob")

    score = None
    parts = []
    if comp is not None:
        score = float(comp)
        parts.append(f"多因子{comp:.0f}")
    if up_prob is not None:
        ml100 = float(up_prob) * 100.0
        score = ml100 if score is None else score * 0.55 + ml100 * 0.45
        parts.append(f"ML上涨概率{up_prob*100:.0f}%")

    if score is None:
        return {"score": None, "verdict": "无程序量化分", "basis": [],
                "note": "多因子与ML均不可用"}

    # regime 轻度风险调节：熊市把分拉向中性50（±压缩）
    reg = regime.get("regime")
    adj_note = ""
    if reg == "bear":
        score = 50.0 + (score - 50.0) * 0.8
        adj_note = "（熊市已降权）"
    elif reg == "bull":
        adj_note = "（牛市）"
    elif reg == "range":
        score = 50.0 + (score - 50.0) * 0.9
        adj_note = "（震荡降权）"

    score = round(max(0.0, min(100.0, score)), 1)
    if score >= 65:
        verdict = "强烈看多"
    elif score >= 55:
        verdict = "看多"
    elif score > 45:
        verdict = "中性"
    elif score > 35:
        verdict = "看空"
    else:
        verdict = "强烈看空"

    basis = list(fac.get("bull_signals", []) or []) + list(fac.get("bear_signals", []) or [])
    if up_prob is not None:
        basis.append(f"[ML] {ml.get('signal', '')}")

    return {"score": score, "verdict": f"程序量化{verdict}",
            "basis": basis[:8],
            "note": f"融合({'+'.join(parts)}){adj_note}"}
