# -*- coding: utf-8 -*-
"""金融 RAG（模块三）：财报/公告/研报索引 → 混合检索（向量+BM25+重排）→ 结论原文引用。

对齐 openbb-rag-financial-research-agent 与 rag-financial-copilot：
- 向量层复用 memory.vector_memory（ChromaDB 或 SQLite 哈希向量，接口统一）；
- BM25 关键词打分（文档集内 idf），与向量分加权重排（alpha 可配）；
- 每个结论附带原文引用 + 证据登记（core.evidence_manager），支持点击回溯。
"""
from __future__ import annotations

import json
import logging
import math
import re
import time
import uuid
from collections import Counter

log = logging.getLogger("stockai.finrag")

from memory.vector_memory import add_document, retrieve_similar  # noqa: E402


def _tokenize(text: str) -> list[str]:
    t = (text or "").lower()
    cjk = re.findall(r"[\u4e00-\u9fff]", t)
    bigrams = [cjk[i] + cjk[i + 1] for i in range(len(cjk) - 1)]
    words = re.findall(r"[a-z0-9]{2,}", t)
    return cjk + bigrams + words


def _idf(doc_tokens: list[Counter], token: str, n_docs: int, eps: float = 1e-6) -> float:
    df = sum(1 for c in doc_tokens if token in c)
    return math.log((n_docs + 1) / (df + 1) + eps)


def _bm25_score(query_tokens: list[str], doc_tokens: Counter,
                doc_tokens_all: list[Counter], n_docs: int,
                k1: float = 1.5, b: float = 0.75) -> float:
    doc_len = sum(doc_tokens.values()) or 1
    avg_len = (sum(sum(c.values()) for c in doc_tokens_all) / max(1, n_docs)) or 1.0
    score = 0.0
    for tok in set(query_tokens):
        tf = doc_tokens.get(tok, 0)
        if not tf:
            continue
        idf = _idf(doc_tokens_all, tok, n_docs)
        score += idf * (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * doc_len / avg_len))
    return score


# ---------------------------------------------------------------------------
# 公开接口
# ---------------------------------------------------------------------------

def index_document(doc_id: str, text: str, meta: dict | None = None) -> int:
    """索引一份财报/公告/研报文本。doc_id 幂等。返回写入条数。"""
    return add_document(doc_id, text, meta)


def _all_docs(top_k_hint: int = 10000) -> list[dict]:
    """取文档集用于 BM25 统计（全量；上限 1 万条防失控）。"""
    try:
        import sqlite3
        from core.config import DATA_DIR
        con = sqlite3.connect(DATA_DIR / "vector_memory.db")
        con.row_factory = sqlite3.Row
        rows = con.execute("SELECT doc_id,text,meta FROM docs LIMIT ?",
                           (top_k_hint,)).fetchall()
        con.close()
        return [dict(r) for r in rows]
    except Exception:  # noqa: BLE001
        return []


def retrieve(query: str, top_k: int = 5, alpha: float = 0.5) -> list[dict]:
    """混合检索：向量分 + BM25 分加权重排。

    返回 [{text, meta, vector_score, bm25_score, final_score}]（final_score 降序）。
    """
    docs = _all_docs(top_k_hint=10000)
    if not docs:
        return []

    q_tokens = _tokenize(query)
    doc_tokens_all = [Counter(_tokenize(d["text"])) for d in docs]
    n_docs = len(docs)

    # 双路候选：向量 topN ∪ BM25 topN（避免 BM25 高命中文档被向量候选截断）
    vec_hits = {d["doc_id"]: d for d in retrieve_similar(query, top_k=max(top_k * 3, 10))}
    bm_all = {d["doc_id"]: _bm25_score(q_tokens, Counter(_tokenize(d["text"])),
                                       doc_tokens_all, n_docs) for d in docs}
    bm_top = set(sorted(bm_all, key=bm_all.get, reverse=True)[:max(top_k * 3, 10)])
    cand_ids = set(vec_hits) | bm_top

    results = []
    for d in docs:
        if d["doc_id"] not in cand_ids:
            continue
        v_score = vec_hits[d["doc_id"]].get("score", 0.0) if d["doc_id"] in vec_hits else 0.0
        bm = bm_all.get(d["doc_id"], 0.0)
        bm_norm = 1.0 - 1.0 / (1.0 + bm)  # sigmoid 归一化到 (0,1)
        final = alpha * v_score + (1 - alpha) * bm_norm
        results.append({
            "doc_id": d["doc_id"], "text": d["text"],
            "meta": json.loads(d["meta"]) if isinstance(d.get("meta"), str) else (d.get("meta") or {}),
            "vector_score": round(v_score, 3), "bm25_score": round(bm, 3),
            "final_score": round(final, 3),
        })
    results.sort(key=lambda x: x["final_score"], reverse=True)
    return results[:top_k]


def analyze_with_rag(query: str, top_k: int = 5, alpha: float = 0.5,
                     llm: callable | None = None,
                     min_score: float | None = None,
                     refuse_on_weak: bool = True) -> dict:
    """RAG 分析：检索 → 证据充分度门控 → 注入上下文 → LLM 生成 → 结论附引用 + 证据登记。

    拒答机制（对齐 VeriFin「找不到证据就拒答」）：
    - 检索为空 → refused（无证据）；
    - 最高相关度 < min_score 阈值 → refused（证据不足，拒绝编造结论）；
    - 通过门控后才调用 LLM；回答必须带 [n] 引用，低引用率时给出提示。

    llm 参数用于注入（测试/自定义后端）；默认走 core.local_fin_engine.chat_finance。
    返回含 citations、evidence_id 与 refused 状态。
    """
    if min_score is None:
        try:
            from core.config import load_config
            min_score = float((load_config().get("rag") or {}).get("min_score", 0.25))
        except Exception:  # noqa: BLE001
            min_score = 0.25

    hits = retrieve(query, top_k=top_k, alpha=alpha)
    evidence_id = uuid.uuid4().hex[:12]

    if not hits:
        return {"ok": False, "refused": True, "evidence_id": evidence_id,
                "reason": "知识库中找不到任何相关证据，拒绝给出结论（请先索引财报/公告/研报，或直接分析）。",
                "answer": "知识库中暂无相关内容（找不到证据，拒绝给出结论）。",
                "citations": [], "engine": "rag-empty"}

    top_score = float(hits[0]["final_score"])
    if refuse_on_weak and top_score < min_score:
        return {"ok": False, "refused": True, "evidence_id": evidence_id,
                "reason": (f"证据不足：最高相关度 {top_score:.3f} 低于阈值 {min_score:.2f}，"
                           f"拒绝给出结论（可补充财报/公告/研报后重试）。"),
                "answer": "资料不足，暂不给出结论（证据门控拒绝）。",
                "candidates": [{"doc_id": h["doc_id"], "text": h["text"][:120],
                                "score": h["final_score"]} for h in hits[:3]],
                "citations": [], "engine": "rag-weak", "top_score": top_score,
                "min_score": min_score}

    context = "\n\n".join(f"[{i + 1}] {h['text'][:600]}" for i, h in enumerate(hits))
    prompt = (
        f"基于以下金融资料回答用户问题。每个关键结论必须标注出处编号，如（[1]）。\n"
        f"资料：\n{context}\n\n问题：{query}\n\n请给出结构化的简洁中文回答。"
        f"若资料不足以支撑结论，请明确说明'资料不足'。")
    system = ("你是金融研究分析师，遵循证据锚定原则："
              "每个结论必须引用资料编号，禁止编造数据。")

    if llm is None:
        from core.local_fin_engine import chat_finance
        answer, engine = chat_finance(prompt, system=system)
        if not answer:
            answer = "（无可用推理引擎：本地金融模型未安装且云端未配置）"
            engine = "unavailable"
    else:
        answer = llm(prompt, system=system) or "（推理引擎未返回内容）"
        engine = "injected"

    # 证据登记：每个引用片段对应一条 claim
    from core.evidence_manager import init, register_claim
    init()
    for i, h in enumerate(hits):
        register_claim(evidence_id, i, f"引用资料[{i + 1}]",
                       h.get("meta", {}).get("source", "financial_rag"),
                       {"doc_id": h["doc_id"], "text": h["text"][:300],
                        "score": h["final_score"]})

    # 低引用率提示（回答未含任何 [n] 引用 → 标记，供 UI 展示）
    import re as _re
    low_citation = not bool(_re.search(r"\[\d+\]", answer or ""))
    return {
        "ok": True, "evidence_id": evidence_id, "answer": answer,
        "engine": engine, "refused": False, "low_citation": low_citation,
        "top_score": top_score, "min_score": min_score,
        "citations": [{"idx": i + 1, "doc_id": h["doc_id"],
                       "text": h["text"][:300],
                       "meta": h.get("meta", {}),
                       "score": h["final_score"]} for i, h in enumerate(hits)],
        "top_k": len(hits), "created_at": time.time(),
    }


def get_evidence(evidence_id: str) -> list[dict]:
    """按分析 ID 取回完整证据链（结论 ↔ 原文 ↔ 数据快照）。"""
    from core.evidence_manager import get_evidence as _get
    return _get(evidence_id)


if __name__ == "__main__":
    index_document("demo-600519-2026Q3",
                   "贵州茅台2026年三季度营收同比增长15%，净利润增长18%，毛利率91%。", {"source": "财报"})
    r = analyze_with_rag("茅台最新业绩如何？", top_k=3, llm=lambda p, system: "营收增长15%，净利润增长18%（[1]）。")
    print(json.dumps({k: v for k, v in r.items() if k != "citations"}, ensure_ascii=False, indent=2))
    print("citations:", len(r["citations"]))
