# -*- coding: utf-8 -*-
"""双层级记忆 · 图层：实体关系图谱（股票 → 行业 → 事件 → 影响链）。

SQLite 图存储（nodes / edges），支持 BFS 邻域查询与链路检索；
Neo4j 未安装时即此实现（零依赖），后续可平滑迁移。
"""
from __future__ import annotations

import json
import time
from collections import deque

from core.config import DATA_DIR

_DB = DATA_DIR / "graph_memory.db"
_SCHEMA = """
CREATE TABLE IF NOT EXISTS nodes (
    entity TEXT PRIMARY KEY,
    type TEXT NOT NULL,              -- stock / industry / event / sector
    props TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS edges (
    src TEXT NOT NULL,
    dst TEXT NOT NULL,
    rel TEXT NOT NULL,               -- belongs_to / impacted_by / leads_to ...
    weight REAL NOT NULL DEFAULT 1.0,
    PRIMARY KEY (src, dst, rel)
);
CREATE INDEX IF NOT EXISTS ix_edges_dst ON edges(dst);
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

def add_entity(entity: str, etype: str, props: dict | None = None) -> None:
    with _conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO nodes(entity,type,props) VALUES(?,?,?)",
            (entity, etype, json.dumps(props or {}, ensure_ascii=False)))


def add_relation(src: str, dst: str, rel: str, weight: float = 1.0) -> None:
    with _conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO edges(src,dst,rel,weight) VALUES(?,?,?,?)",
            (src, dst, rel, weight))


def neighbors(entity: str, rel: str | None = None) -> list[dict]:
    with _conn() as c:
        if rel:
            rows = c.execute(
                "SELECT dst,rel,weight FROM edges WHERE src=? AND rel=?", (entity, rel)).fetchall()
        else:
            rows = c.execute(
                "SELECT dst,rel,weight FROM edges WHERE src=?", (entity,)).fetchall()
    return [dict(r) for r in rows]


def query_entity_relations(entity: str, depth: int = 2) -> dict:
    """BFS 邻域查询。返回 {nodes:[{entity,type,props}], edges:[{src,rel,dst}]}。"""
    if depth < 1:
        depth = 1
    with _conn() as c:
        def _node(e):
            return c.execute("SELECT * FROM nodes WHERE entity=?", (e,)).fetchone()

        start = _node(entity)
        nodes, edges = {}, []
        if start is None:
            return {"nodes": [], "edges": []}
        nodes[entity] = dict(start)
        nodes[entity]["props"] = json.loads(nodes[entity]["props"])
        seen = {entity}
        q = deque([(entity, 0)])
        while q:
            cur, d = q.popleft()
            if d >= depth:
                continue
            for e in c.execute("SELECT * FROM edges WHERE src=?", (cur,)).fetchall():
                edges.append({"src": e["src"], "rel": e["rel"], "dst": e["dst"]})
                if e["dst"] not in seen:
                    seen.add(e["dst"])
                    nd = _node(e["dst"])
                    if nd:
                        nd = dict(nd)
                        nd["props"] = json.loads(nd["props"])
                        nodes[e["dst"]] = nd
                        q.append((e["dst"], d + 1))
    return {"nodes": list(nodes.values()), "edges": edges}


def chain(entity_a: str, entity_b: str, max_hops: int = 4) -> list[list[str]]:
    """影响链检索（BFS 找路径）。返回所有 ≤max_hops 的路径。"""
    with _conn() as c:
        adj = {}
        for r in c.execute("SELECT src,dst FROM edges").fetchall():
            adj.setdefault(r["src"], []).append(r["dst"])
    paths, q = [], deque([(entity_a, [entity_a])])
    while q:
        cur, path = q.popleft()
        if cur == entity_b:
            paths.append(path)
            continue
        if len(path) >= max_hops:
            continue
        for nxt in adj.get(cur, []):
            if nxt not in path:
                q.append((nxt, path + [nxt]))
    return paths


def seed_demo() -> int:
    """写入演示种子关系（幂等），供知识库浏览。"""
    demo = [
        ("600519", "stock", {"name": "贵州茅台", "sector": "白酒"}),
        ("白酒", "industry", {}), ("白酒", "sector", {}),
        ("消费", "sector", {}),
        ("行业整顿", "event", {"date": "2026-01"}),
        ("需求复苏", "event", {"date": "2026-03"}),
    ]
    for e, t, p in demo:
        add_entity(e, t, p)
    rels = [("600519", "白酒", "belongs_to"), ("白酒", "消费", "belongs_to"),
            ("行业整顿", "白酒", "impacted_by"),
            ("需求复苏", "白酒", "impacted_by"),
            ("600519", "行业整顿", "affected_by")]
    for s, d, r in rels:
        add_relation(s, d, r)
    return len(rels)


def stats() -> dict:
    with _conn() as c:
        n = c.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
        e = c.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
    return {"nodes": n, "edges": e}
