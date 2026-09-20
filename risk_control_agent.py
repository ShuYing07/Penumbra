# -*- coding: utf-8 -*-
"""风控审查Agent：独立审查辩论结论，检查过度乐观/尾部风险/数据缺失。

风控有权否决或降级最终结论。参考TradingAgents-AShare的风控环节。
"""
from __future__ import annotations

import logging

log = logging.getLogger("stockai.risk_control")


def risk_review(debate_result: dict) -> dict:
    """审查多空辩论结果，返回风控意见。

    debate_result: {bull_case: [...], bear_case: [...], confidence: int, ...}
    返回: {approved: bool, verdict: str, warnings: [...], adjusted_confidence: int}
    """
    bull = debate_result.get("bull_case") or []
    bear = debate_result.get("bear_case") or []
    confidence = debate_result.get("confidence", 50)

    warnings = []

    # 检查1：看多论点数量远多于看空 → 可能过度乐观
    if len(bull) > len(bear) * 2:
        warnings.append("看多论点数量显著多于看空，存在过度乐观偏差")
        confidence = min(confidence, 50)

    # 检查2：看空论点过少 → 尾部风险被忽视
    if len(bear) < 2:
        warnings.append("看空论点不足，可能忽视尾部风险")
        confidence = min(confidence, 60)

    # 检查3：置信度过高但缺乏数据支撑
    if confidence >= 80 and len(bull) + len(bear) < 3:
        warnings.append("置信度过高但论点数量不足，可能缺乏数据支撑")
        confidence = min(confidence, 55)

    # 检查4：完全没有风险提示
    if not bear:
        warnings.append("无看空论点，结论可能存在确认偏误")
        confidence = min(confidence, 40)

    # 判定
    approved = confidence >= 50 and len(warnings) <= 1
    verdict = "通过" if approved else "需谨慎"

    if warnings:
        verdict = "降级：存在风险提示" if not approved else "通过（有警告）"

    return {
        "approved": approved,
        "verdict": verdict,
        "warnings": warnings,
        "adjusted_confidence": confidence,
        "review_note": (
            f"风控审查：{verdict}。"
            f"原始置信度{debate_result.get('confidence', 50)}% → "
            f"调整后{confidence}%。"
            + (f" 警告：{'; '.join(warnings)}" if warnings else " 无警告。")
        ),
    }


if __name__ == "__main__":
    # 自测
    test = {
        "bull_case": ["茅台品牌护城河深", "现金流稳定", "分红比例提升", "国际市场扩张"],
        "bear_case": ["宏观经济下行"],
        "confidence": 85,
    }
    result = risk_review(test)
    for k, v in result.items():
        print(f"  {k}: {v}")
