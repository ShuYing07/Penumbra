# -*- coding: utf-8 -*-
"""混合推理框架：任务类型 → 动态策略 + 置信度门控。

- 确定性任务（财务计算/指标校验）→ 结构化：规则引擎 + 图/向量精确召回；
- 对话式任务（问答/摘要）→ 检索增强：向量 + BM25；
- 置信度门控：融合得分低于阈值时拒绝给出结论，返回“数据不足”。

策略由 config.REASONING_STRATEGY 控制（auto / structured / retrieval），
调用方可按 task_type 覆盖。
"""
from __future__ import annotations

import re

from core import config
from memory.hybrid_memory import search as _mem_search, select_strategy as _sel

_STRATEGY_ENV = getattr(config, "REASONING_STRATEGY", "auto")
_CONF_THRESHOLD = 0.15  # 融合得分阈值


def resolve_strategy(task_type: str | None = None) -> str:
    """三级决策：config → task_type → 默认 auto。"""
    if _STRATEGY_ENV != "auto":
        return _STRATEGY_ENV
    return _sel(task_type or "auto")


def gate(confidence: float) -> bool:
    """置信度门控：≤阈值即拦截（数据不足）。"""
    return confidence <= _CONF_THRESHOLD


def reason(task_type: str, question: str, context: dict | None = None) -> dict:
    """混合推理入口。返回 {strategy, confidence, answer, evidence, gated}。

    gated=True 表示数据不足被门控拦截，不输出结论性内容（合规）。
    """
    context = context or {}
    strategy = resolve_strategy(task_type)

    # ---- 结构化分支（确定性任务）----
    if strategy == "structured":
        hits = _mem_search(question, top_k=3, task_type="deterministic")
        # 结构化：有图/规则命中的条目权重更高
        evidence = [h for h in hits if h.get("engine") in ("graph", "chromadb")]
        base = max((h["score"] for h in hits), default=0.0)
        confidence = round(min(base + 0.1, 0.95), 2)
        if evidence:
            answer = "结构化检索命中：" + "；".join(
                h["text"][:60] for h in evidence[:2])
        else:
            answer = "未命中结构化记忆（规则/图谱）"
    # ---- 检索分支（对话式任务）----
    else:
        hits = _mem_search(question, top_k=5, task_type="conversational")
        evidence = hits
        confidence = round(max((h["score"] for h in hits), default=0.0), 2)
        if hits:
            answer = hits[0]["text"][:200]
        else:
            answer = "检索未返回相关内容"

    # ---- 置信度门控 ----
    if gate(confidence):
        return {
            "strategy": strategy, "confidence": confidence,
            "answer": "数据不足：当前可用的记忆与检索结果无法支撑可靠回答。",
            "evidence": evidence, "gated": True,
        }
    return {"strategy": strategy, "confidence": confidence,
            "answer": answer, "evidence": evidence, "gated": False}


def gated_decision(task_type: str, question: str, context: dict | None = None) -> dict:
    """对外结论出口：gated=True 时禁止产出结论性内容（合规红线）。"""
    r = reason(task_type, question, context)
    if r["gated"]:
        r["answer"] = "（数据不足，已拒绝生成结论。请补充数据后再试。）"
    return r
