# -*- coding: utf-8 -*-
"""模块三 · 领域微调与 RAG 增强：unit tests。

覆盖：文档索引、混合检索（向量+BM25）、重排排序、RAG 结论带引用、
证据链登记与回溯、本地金融引擎配置解析与降级语义。
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("STOCKAI_MOCK", "1")

import uuid

from core.financial_rag import (analyze_with_rag, get_evidence, index_document,
                                retrieve)
from core.local_fin_engine import LocalFinEngine, chat_finance, _configured_model


def _unique_docs():
    uid = uuid.uuid4().hex[:8]
    index_document(f"{uid}-mt",
                   f"贵州茅台2026年三季度营收同比增长15% {uid} 净利润增长18%，毛利率91%。",
                   {"source": "财报", "stock": "600519"})
    index_document(f"{uid}-nd",
                   f"宁德时代发布新一代电池，能量密度提升30% {uid} 获多家车企订单。",
                   {"source": "公告", "stock": "300750"})
    index_document(f"{uid}-bd",
                   f"比亚迪海外销量创新高，欧洲市场增长显著 {uid}。",
                   {"source": "研报", "stock": "002594"})
    return uid


def test_index_and_mixed_retrieve():
    uid = _unique_docs()
    # 用 uid（唯一关键词）做确定性检索：BM25 精确命中刚插入的文档
    hits = retrieve(f"{uid} 营收", top_k=3)
    assert hits, "应返回检索结果"
    assert any(uid in h["doc_id"] for h in hits), "uid 文档应进入 top_k"
    # 分数字段齐全且降序
    scores = [h["final_score"] for h in hits]
    assert scores == sorted(scores, reverse=True)
    assert all({"vector_score", "bm25_score", "final_score"} <= set(h) for h in hits)


def test_bm25_prefers_keyword_hit():
    uid = _unique_docs()
    hits = retrieve(uid, top_k=1)
    assert hits and uid in hits[0]["doc_id"], "BM25 应对唯一关键词精确命中"


def test_rag_analysis_with_citations():
    uid = _unique_docs()
    r = analyze_with_rag(f"{uid} 营收", top_k=2,
                         llm=lambda p, system: "营收增长15%，净利润增长18%（[1]）。")
    assert r["ok"] and r["evidence_id"]
    assert r["citations"] and len(r["citations"]) == 2
    assert r["engine"] == "injected"
    assert any(uid in c["doc_id"] for c in r["citations"]), "uid 文档应进入引用"
    # 证据链可回溯
    ev = get_evidence(r["evidence_id"])
    assert ev and len(ev) >= 1
    assert ev[0].get("claim") or ev[0].get("source")


def test_rag_empty_knowledge():
    r = analyze_with_rag("不存在的内容xyzzy", top_k=2,
                         llm=lambda p, system: "nothing")
    # 命中不保证，但应返回结构化结果（ok 可能 False）
    assert "evidence_id" in r and "answer" in r
    assert r.get("refused") is not None, "拒答状态字段必须存在"


def test_refuse_on_weak_evidence():
    """VeriFin 式门控：证据不足必须拒答，即使检索非空。"""
    uid = _unique_docs()
    # 强制超高阈值：即使 uid 精确命中（~0.85）也低于 0.99 → 拒答
    r = analyze_with_rag(f"{uid} 营收", top_k=2, min_score=0.99,
                         llm=lambda p, system: "营收增长15%")
    assert r["ok"] is False
    assert r["refused"] is True
    assert "证据不足" in r["reason"]
    assert r["engine"] == "rag-weak"
    assert r["top_score"] < r["min_score"]


def test_refuse_passed_when_evidence_strong():
    """证据充分时必须通过门控并正常生成（不误拒）。"""
    uid = _unique_docs()
    r = analyze_with_rag(f"{uid} 营收", top_k=2, min_score=0.05,
                         llm=lambda p, system: "营收增长15%，净利润增长18%（[1]）。")
    assert r["ok"] is True and r["refused"] is False
    assert r["top_score"] >= r["min_score"]


def test_fin_engine_config_resolution():
    assert isinstance(_configured_model(), str) and _configured_model()
    eng = LocalFinEngine()
    assert eng.model_name
    # 无 Ollama 时：is_ollama_ready False 或 generate 返回 None —— 降级语义安全
    text, model = eng.generate("测试", "")
    if model is None:
        assert text is None


def test_chat_finance_never_raises():
    # 任何环境（无模型/无key）都不应抛异常；返回二元组
    text, engine = chat_finance("你好", "", timeout=5)
    assert isinstance(text, str) and isinstance(engine, str)
    assert engine in ("local-finance(", "local-fallback", "cloud-fallback", "unavailable") \
        or engine.startswith("local-finance")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"[ok] {fn.__name__}")
    print(f"\nALL PASS ({len(fns)})")
