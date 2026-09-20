# -*- coding: utf-8 -*-
"""学习资源 RAG 库（chromadb 持久化 + 离线哈希嵌入）。

设计取舍（详见知识库 02/01§6）：
- 不用在线 embedding API（DeepSeek 无 embedding 端点，其他要 key/联网/花钱）；
- 不用 sentence-transformers（torch 重依赖，与 exe 打包目标冲突）；
- 采用字符 n-gram 哈希嵌入（512 维，L2 归一化，hashing trick）：中文 char-bigram
  + 英文词 token，离线、零依赖、确定性；语义精度弱于神经嵌入，但对
  "同类新闻/报告/反思"相关检索足够 MVP，后续可平滑升级 BGE-M3。
- 调 chromadb 时一律显式传 embeddings=，不依赖其 EmbeddingFunction 协议（跨版本稳定）。
"""
from __future__ import annotations

import hashlib
import logging
import math
import re

from core.config import DATA_DIR, REPORT_DIR
from core.data.cache import get_conn

log = logging.getLogger("stockai.rag")

CHROMA_DIR = DATA_DIR / "chroma"
_DIM = 512

_client = None
_collection = None


class HashEmbedder:
    """字符 n-gram 哈希嵌入：中文 bigram+单字、英文/数字词，带符号哈希，L2 归一化。"""

    def __init__(self, dim: int = _DIM):
        self.dim = dim

    def encode(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        text = (text or "").lower()
        cjk = re.findall(r"[\u4e00-\u9fff]", text)
        for ch in cjk:
            self._bump(vec, ch)
        for i in range(len(cjk) - 1):
            self._bump(vec, cjk[i] + cjk[i + 1])
        for w in re.findall(r"[a-z0-9]{2,}", text):
            self._bump(vec, w)
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    def _bump(self, vec: list[float], token: str) -> None:
        h = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        idx = int.from_bytes(h[:4], "little") % self.dim
        sign = 1.0 if (h[4] & 1) else -1.0
        vec[idx] += sign


def _get_collection():
    global _client, _collection
    if _collection is not None:
        return _collection
    import chromadb
    from chromadb.config import Settings

    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    _client = chromadb.PersistentClient(
        path=str(CHROMA_DIR),
        settings=Settings(anonymized_telemetry=False, allow_reset=True))
    _collection = _client.get_or_create_collection(
        "learning", metadata={"hnsw:space": "cosine"})
    return _collection


def _embed(texts: list[str]) -> list[list[float]]:
    emb = HashEmbedder()
    return [emb.encode(t) for t in texts]


def _doc_id(kind: str, ref: str, idx: int = 0) -> str:
    return hashlib.md5(f"{kind}|{ref}|{idx}".encode("utf-8")).hexdigest()


def add_docs(docs: list[dict], batch: int = 128) -> int:
    """入库。docs 元素：{text, kind(report/news/reflection/resource), ticker, date, title, ref}。

    按 kind+ref+序号 生成幂等 id，重复入库自动跳过。返回实际新增条数。
    """
    if not docs:
        return 0
    col = _get_collection()
    added = 0
    for i in range(0, len(docs), batch):
        chunk = docs[i:i + batch]
        ids = [_doc_id(d["kind"], d.get("ref", ""), i + j) for j, d in enumerate(chunk)]
        exist = set(col.get(ids=ids)["ids"])
        new = [(d, _id) for d, _id in zip(chunk, ids) if _id not in exist]
        if not new:
            continue
        ds, idds = zip(*new)
        col.add(
            ids=list(idds),
            documents=[d["text"] for d in ds],
            embeddings=_embed([d["text"] for d in ds]),
            metadatas=[{"kind": d["kind"], "ticker": (d.get("ticker") or "")[:20],
                        "date": (d.get("date") or "")[:10],
                        "title": (d.get("title") or "")[:200],
                        "ref": (d.get("ref") or "")[:200]} for d in ds])
        added += len(idds)
    if added:
        log.info("RAG 入库 %d 条（库内共 %d）", added, col.count())
    return added


def index_reports(limit: int = 50) -> int:
    """data/reports/*.md 按小节切块入库（最新优先）。"""
    docs: list[dict] = []
    files = sorted(REPORT_DIR.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]
    for fp in files:
        try:
            md = fp.read_text(encoding="utf-8")
        except Exception:  # noqa: BLE001
            continue
        for j, sec in enumerate(re.split(r"\n(?=#+ )", md)):
            sec = sec.strip()
            if len(sec) < 40:
                continue
            head = sec.splitlines()[0].lstrip("# ").strip()
            docs.append({"text": sec[:2000], "kind": "report", "ticker": "",
                         "date": fp.stem.rsplit("_", 1)[-1] if "_" in fp.stem else "",
                         "title": f"{fp.stem} · {head}", "ref": f"{fp.name}#{j}"})
    return add_docs(docs)


def index_news(ticker: str | None = None, limit: int = 300) -> int:
    """SQLite news 表入库（可按标的过滤）。"""
    from core.data.cache import load_news
    rows = load_news(ticker=ticker, limit=limit)
    docs = [{"text": f"{r['title']}\n{r.get('content') or ''}"[:2000], "kind": "news",
             "ticker": ticker or "", "date": (r.get("published_at") or "")[:10],
             "title": r["title"], "ref": r["url"]}
            for r in rows if r.get("title")]
    return add_docs(docs)


def index_reflections(limit: int = 200) -> int:
    """已评估决策的反思入库——自我经验也是学习资源。"""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT id, ticker, ts, action, realized_return_pct, reflection, summary
               FROM decisions WHERE evaluated=1 ORDER BY id DESC LIMIT ?""",
            (limit,)).fetchall()
    docs = []
    for did, ticker, ts, action, ret, refl, summary in rows:
        text = (f"标的{ticker} 决策[{action}] 时间{(ts or '')[:10]} 实际涨跌{ret}%。\n"
                f"结论：{summary or ''}\n反思：{refl or ''}")
        docs.append({"text": text[:2000], "kind": "reflection", "ticker": ticker or "",
                     "date": (ts or "")[:10], "title": f"决策#{did} {action} 实际{ret}%",
                     "ref": f"decision:{did}"})
    return add_docs(docs)


def index_analysis(state: dict) -> int:
    """每次分析完成后自动入库：结论卡片 + 当次新闻（失败不影响主流程）。"""
    try:
        from core.report import render
        ticker = state.get("ticker", "")
        f = state.get("final", {})
        docs = [{"text": (f"标的{ticker} 分析结论[{f.get('action')}] "
                          f"仓位{f.get('position_pct')}% 置信{f.get('confidence')}%"
                          f"{('：' + f['summary']) if f.get('summary') else ''}"),
                 "kind": "report", "ticker": ticker, "date": state.get("asof", ""),
                 "title": f"{ticker} 结论 {f.get('action')}",
                 "ref": f"analysis:{ticker}:{state.get('asof')}"}]
        for n in (state.get("news") or [])[:20]:
            if n.get("title"):
                docs.append({"text": f"{n['title']}\n{n.get('content') or ''}"[:2000],
                             "kind": "news", "ticker": ticker,
                             "date": (n.get("published_at") or "")[:10],
                             "title": n["title"],
                             "ref": n.get("url") or f"{ticker}:{n['title']}"})
        return add_docs(docs)
    except Exception as e:  # noqa: BLE001
        log.warning("当次分析入库失败：%s", e)
        return 0


def search(query: str, kind: str | None = None, n: int = 8) -> list[dict]:
    """混合检索：向量（语义）+ BM25（关键词）融合，取并集重排。

    返回 [{doc, meta, score}]，score=融合分（0~1，越大越相关）。
    """
    col = _get_collection()
    total = col.count()
    if not query.strip() or total == 0:
        return []

    # 向量检索（语义）
    vec_res = col.query(query_embeddings=_embed([query]), n_results=min(n * 2, total),
                        where={"kind": kind} if kind else None,
                        include=["documents", "metadatas", "distances"])
    vec_hits = {}
    for d, m, dist in zip(vec_res["documents"][0], vec_res["metadatas"][0],
                          vec_res["distances"][0]):
        key = m.get("ref") or d[:80]
        vec_hits[key] = {"doc": d, "meta": m,
                         "vec_score": round(max(0.0, 1.0 - float(dist)), 3)}

    # BM25 关键词检索
    bm25_hits = _bm25_search(query, kind=kind, n=n * 2)

    # 融合：并集，向量分*0.6 + BM25分*0.4
    fused = {}
    for key, hit in vec_hits.items():
        fused[key] = {**hit, "bm25_score": 0.0, "score": hit["vec_score"] * 0.6}
    for key, hit in bm25_hits.items():
        if key in fused:
            fused[key]["bm25_score"] = hit["score"]
            fused[key]["score"] = fused[key]["vec_score"] * 0.6 + hit["score"] * 0.4
        else:
            fused[key] = {"doc": hit["doc"], "meta": hit["meta"],
                          "vec_score": 0.0, "bm25_score": hit["score"],
                          "score": hit["score"] * 0.4}

    ranked = sorted(fused.values(), key=lambda x: x["score"], reverse=True)[:n]
    for r in ranked:
        r["score"] = round(r["score"], 3)
    return ranked


def _bm25_search(query: str, kind: str | None = None, n: int = 8) -> dict:
    """BM25关键词检索。返回 {ref_key: {doc, meta, score}}，score归一化到0~1。"""
    try:
        from rank_bm25 import BM25Okapi
    except ImportError:
        return {}

    col = _get_collection()
    # 拉全部文档建索引（规模可控：几百~几千条）
    batch = col.get(limit=col.count(), include=["documents", "metadatas"])
    docs = batch["documents"]
    metas = batch["metadatas"]
    if not docs:
        return {}

    # 简单分词：中文按字、英文按词
    import re as _re

    def _tokenize(text: str) -> list[str]:
        tokens = _re.findall(r"[\u4e00-\u9fff]|[a-z0-9]+", (text or "").lower())
        return tokens

    corpus_tokens = [_tokenize(d) for d in docs]
    bm25 = BM25Okapi(corpus_tokens)
    query_tokens = _tokenize(query)
    scores = bm25.get_scores(query_tokens)

    # 过滤kind + 取top
    results = []
    for i, score in enumerate(scores):
        m = metas[i]
        if kind and m.get("kind") != kind:
            continue
        results.append((score, docs[i], m))
    results.sort(key=lambda x: x[0], reverse=True)
    results = results[:n]

    if not results:
        return {}
    max_s = results[0][0] or 1.0
    out = {}
    for score, doc, m in results:
        key = m.get("ref") or doc[:80]
        out[key] = {"doc": doc, "meta": m,
                    "score": round(max(0.0, score / max_s), 3)}
    return out


def stats() -> dict:
    col = _get_collection()
    total = col.count()
    by_kind: dict[str, int] = {}
    if total:
        for m in col.get(include=["metadatas"])["metadatas"]:
            by_kind[m["kind"]] = by_kind.get(m["kind"], 0) + 1
    return {"total": total, "by_kind": by_kind}
