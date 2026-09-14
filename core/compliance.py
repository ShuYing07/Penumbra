# -*- coding: utf-8 -*-
"""AI 输出合规过滤：把可能构成"荐股"的敏感词替换为【已过滤】。

工具定位为客观数据展示，不输出任何买卖建议/价格预测/个股推荐。
"""
from __future__ import annotations

# 敏感词 → 替换标记（保守替换，避免越界成投资建议）
_FORBIDDEN = ["买入", "卖出", "推荐", "目标价", "必涨", "稳赚", "涨停", "跌停", "抄底", "逃顶", "荐股"]
# 指导性词汇（不替换，仅用于日志提示）
_GUIDE_WORDS = ["建议", "应该", "应当"]

DISCLAIMER_SUFFIX = (
    "\n———\n⚠️ 本分析仅为客观数据展示，不构成投资建议。投资有风险，入市需谨慎。\n"
)


def sanitize_ai_output(text: str) -> str:
    """把敏感词替换为【已过滤】；已含免责声明则不重复追加。"""
    if not text:
        return text or ""
    out = text
    for w in _FORBIDDEN:
        if w in out:
            out = out.replace(w, "【已过滤】")
    if "不构成投资建议" not in out:
        out = out.rstrip() + DISCLAIMER_SUFFIX
    return out
