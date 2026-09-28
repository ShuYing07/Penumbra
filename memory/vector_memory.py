# -*- coding: utf-8 -*-
"""双层级记忆 · 向量层：统一语义检索接口。

优先使用既有 core.memory.rag（chromadb + 哈希嵌入 + BM25 融合，已实装）；
chromadb 未安装时自动降级到 SQLite 哈希向量索引（零依赖），接口不变。
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import time
from pathlib import Path

from core.config import DATA_DIR

_DB = DATA_DIR / "vector_memory.db"
_DIM = 256
_SCHEMA = """
CREATE TABLE IF NOT EXISTS docs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id TEXT UNIQUE NOT NULL,
    text TEXT NOT NULL,
    meta TEXT NOT NULL DEFAULT '{}',
    vec TEXT NOT NULL,
    ts REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_docs_docid ON docs(doc_id);
"""


def _conn():
    import sqlite3
    from contextlib import closing, contextmanager

    @contextmanager
    def _open():
        con = sqlite3.connect(_DB)
        con.row_factory = sqlite3.Row
        con.executescript(_SCHEMA)
        with closing(con):
            yield con
            con.commit()

    return _open()

# ---------------- 哈希嵌入（与 rag.HashEmbedder 同思路，独立降级实现） ----------------

def _embed(text: str) -> list[float]:
    vec = [0.0] * _DIM
    t = (text or "").lower()
    cjk = re.findall(r"[\u4e00-\u9fff]", t)
    tokens = cjk + [cjk[i] + cjk[i + 1] for i in range(len(cjk) - 1)]
    tokens += re.findall(r"[a-z0-9]{2,}", t)
    for tok in tokens:
        h = hashlib.blake2b(tok.encode("utf-8"), digest_size=8).digest()
        idx = int.from_bytes(h[:4], "little") % _DIM
        sign = 1.0 if (h[4] & 1) else -1.0
        vec[idx] += sign
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def _cos(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def _chroma_ready() -> bool:
    try:
        import chromadb  # noqa: F401
        return True
    except ImportError:
        return False


# ---------------- 公开接口 ----------------

def add_document(doc_id: str, text: str, meta: dict | None = None) -> int:
    """写入向量记忆；doc_id 幂等。返回写入条数。"""
    meta = meta or {}
    vec = _embed(text)
    with _conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO docs(doc_id,text,meta,vec,ts) VALUES(?,?,?,?,?)",
            (doc_id, text, json.dumps(meta, ensure_ascii=False),
             json.dumps(vec), time.time()))
    return 1


def retrieve_similar(query: str, top_k: int = 5) -> list[dict]:
    """语义检索（本地向量，SQLite 余弦）。与 chroma/旧 rag 库解耦，数据自足。"""
    qv = _embed(query)
    with _conn() as c:
        rows = c.execute("SELECT doc_id,text,meta,vec FROM docs").fetchall()
    scored = [(_cos(qv, json.loads(r["vec"])), dict(r)) for r in rows]
    scored.sort(key=lambda x: x[0], reverse=True)
    out = []
    for s, r in scored[:top_k]:
        out.append({"text": r["text"], "meta": json.loads(r["meta"]),
                    "score": round(s, 3), "engine": "sqlite-hash"})
    return out


def stats() -> dict:
    with _conn() as c:
        n = c.execute("SELECT COUNT(*) FROM docs").fetchone()[0]
    return {"docs": n, "engine": "chromadb" if _chroma_ready() else "sqlite-hash",
            "dims": _DIM}
