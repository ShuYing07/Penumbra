# -*- coding: utf-8 -*-
"""AI 输出合规过滤：拦截所有指向具体品种的结论性表述。

工具定位为客观数据展示，不输出任何买卖建议/价格预测/个股推荐。
"""
from __future__ import annotations

# 禁用词 → 替换标记
_FORBIDDEN = [
    "买入", "卖出", "推荐", "目标价", "必涨", "稳赚", "涨停", "跌停",
    "抄底", "逃顶", "荐股", "满仓", "清仓", "止损", "止盈",
    "可以关注", "值得布局", "逢低吸纳", "建议持有", "强烈推荐",
    "建议买入", "建议卖出", "建议加仓", "建议减仓",
    "第一目标", "第二目标", "压力位", "支撑位",
]

DISCLAIMER_SUFFIX = (
    "\n———\n"
    "⚠️ 本工具为开源金融数据分析软件，仅供研究学习使用。"
    "不提供任何证券投资分析、预测或建议，不构成任何投资建议，不是荐股软件。"
    "开发者不具备证券投资咨询业务资格。投资有风险，入市需谨慎。\n"
)


def sanitize_ai_output(text: str) -> str:
    """把敏感词替换为【已过滤】；自动追加免责声明。"""
    if not text:
        return text or ""
    out = text
    for w in _FORBIDDEN:
        if w in out:
            out = out.replace(w, "【已过滤】")
    if "不构成投资建议" not in out:
        out = out.rstrip() + DISCLAIMER_SUFFIX
    return out


def has_violation(text: str) -> bool:
    """检查是否有违规词（用于审计记录）。"""
    return any(w in text for w in _FORBIDDEN)