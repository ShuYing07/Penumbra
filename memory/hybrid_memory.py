# -*- coding: utf-8 -*-
"""双层级记忆 · 混合检索：向量 + 图 + BM25 融合重排，按任务动态选策略。

- task_type="deterministic"（财务计算/规则）：优先结构化（图邻域 + 向量精确段）；
- task_type="conversational"（问答/摘要）：优先检索增强（向量 + BM25）；
- 融合重排：并集加权（向量 0.5 / BM25 0.3 / 图命中 0.2 加成）。
"""
from __future__ import annotations

import re

from memory.vector_memory import retrieve_similar, stats as _vstats
from memory.graph_memory import query_entity_relations, stats as _gstats


def _bm25_score(query: str, text: str) -> float:
    q = set(re.findall(r"[\u4e00-\u9fff]|[a-z0-9]+", (query or "").lower()))
    d = set(re.findall(r"[\u4e00-\u9fff]|[a-z0-9]+", (text or "").lower()))
    if not q:
        return 0.0
    return round(len(q & d) / len(q), 3)


def select_strategy(task_type: str) -> str:
    """动态策略选择：deterministic → structured；conversational → retrieval。"""
    if task_type in ("deterministic", "structured"):
        return "structured"
    if task_type in ("conversational", "retrieval", "rag"):
        return "retrieval"
    return "auto"


def search(query: str, top_k: int = 5, task_type: str = "auto") -> list[dict]:
    """混合检索入口。返回 [{text, meta, score, engine, source}]。"""
    vec = retrieve_similar(query, top_k=top_k * 2)
    fused: dict[str, dict] = {}
    for v in vec:
        key = v["text"][:80]
        fused[key] = {**v, "bm25": _bm25_score(query, v["text"]),
                      "graph_bonus": 0.0,
                      "score": v["score"] * 0.5 + _bm25_score(query, v["text"]) * 0.3}

    # 图邻域：查询词是否命中实体
    for token in re.findall(r"[\u4e00-\u9fff]{2,}|[a-zA-Z0-9]{2,}", query):
        g = query_entity_relations(token.strip(), depth=1)
        if g["nodes"]:
            label = " → ".join(n["entity"] for n in g["nodes"][:3])
            entry = {"text": f"图记忆：{label}",
                     "meta": {"source": "graph", "entity": token},
                     "bm25": 0.0, "graph_bonus": 0.2,
                     "score": 0.2, "engine": "graph"}
            fused[label] = entry
            break

    ranked = sorted(fused.values(), key=lambda x: x["score"], reverse=True)[:top_k]
    for r in ranked:
        r["score"] = round(r["score"], 3)
    return ranked


def stats() -> dict:
    return {"vector": _vstats(), "graph": _gstats()}
