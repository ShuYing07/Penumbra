# -*- coding: utf-8 -*-
"""动态知识图谱（HERMES 模块）。

- 时序感知实体关系：实体/关系均带时间戳，关系支持 valid_from / valid_to 生效区间；
- 演化机制：新事件按时间衰减更新关系权重，过期关系自动降权/摘除；
- 金融实体识别与链接：基于词典（股票代码/名称/行业/指数）的轻量 NER + 实体链接；
- 持久化：内存 + SQLite（可选），失败自动降级内存模式。

设计要点（吸收 AlphaMesh 图记忆 + 时序图谱的教训）：
- 实体 ID 统一规范（股票用 ticker，概念/行业用规范化 slug），避免重复实体；
- 关系方向明确（subject → object，rel_type 语义化），支持影响链查询；
- 时效性优先：分析引用关系时按生效区间过滤，避免"旧关系当新事实"。
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from collections import defaultdict

log = logging.getLogger("stockai.hermes.kg")

# 内置金融词典（示例级；正式数据可扩展）
_STOCK_ALIASES: dict[str, str] = {
    "600519": "SH600519", "sh600519": "SH600519", "茅台": "SH600519",
    "贵州茅台": "SH600519", "apple": "AAPL", "aapl": "AAPL",
    "腾讯控股": "HK00700", "腾讯": "HK00700", "tencent": "HK00700",
}
_INDEX_ALIASES: dict[str, str] = {
    "上证指数": "IDX000001", "沪深300": "IDX000300", "深证成指": "IDX399001",
    "创业板指": "IDX399006",
}
_INDUSTRIES = {"白酒", "消费", "新能源", "科技", "半导体", "医药", "金融", "地产",
               "军工", "汽车", "AI", "机器人"}


def financial_ner(text: str) -> list[dict]:
    """金融实体识别：返回 [{entity_id, kind, mention}]。"""
    if not text:
        return []
    low = text.lower()
    out: list[dict] = []
    seen = set()
    for alias, eid in {**_STOCK_ALIASES, **_INDEX_ALIASES}.items():
        if alias.lower() in low and eid not in seen:
            seen.add(eid)
            kind = "index" if eid.startswith("IDX") else "stock"
            out.append({"entity_id": eid, "kind": kind, "mention": alias})
    for ind in _INDUSTRIES:
        if ind in text:
            eid = f"IND:{ind}"
            if eid not in seen:
                seen.add(eid)
                out.append({"entity_id": eid, "kind": "industry", "mention": ind})
    return out


def link_entities(text: str, candidates: list[dict] | None = None) -> list[dict]:
    """实体链接：把识别出的实体对齐到图谱节点（带置信度）。"""
    ents = candidates or financial_ner(text)
    for e in ents:
        e["confidence"] = 0.9 if e["kind"] in ("stock", "index") else 0.75
    return ents


class DynamicKG:
    """动态知识图谱（时序演化）。"""

    def __init__(self, db_path=None, decay_half_life_days: int = 90):
        self.decay_half_life_days = decay_half_life_days
        self._lock = threading.Lock()
        self.entities: dict[str, dict] = {}
        self.relations: list[dict] = []  # {src,dst,rel,weight,valid_from,valid_to,evidence}
        self._seq = 0
        self._db_path = db_path
        self._conn = None
        if db_path:
            self._init_db()

    # ---------- 持久化（SQLite，可选） ----------
    def _init_db(self) -> None:
        try:
            import sqlite3
            self._conn = sqlite3.connect(self._db_path)
            self._conn.execute("CREATE TABLE IF NOT EXISTS kg_entities("
                               "eid TEXT PRIMARY KEY, kind TEXT, attrs TEXT, ts REAL)")
            self._conn.execute("CREATE TABLE IF NOT EXISTS kg_relations("
                               "seq INTEGER PRIMARY KEY AUTOINCREMENT, src TEXT, dst TEXT,"
                               "rel TEXT, weight REAL, valid_from REAL, valid_to REAL,"
                               "evidence TEXT)")
            self._conn.commit()
        except Exception as e:  # noqa: BLE001
            log.warning("KG 持久化不可用，降级内存模式: %s", e)
            self._conn = None

    def persist(self) -> int:
        if self._conn is None:
            return 0
        try:
            with self._conn:
                self._conn.execute("DELETE FROM kg_entities")
                self._conn.execute("DELETE FROM kg_relations")
                for eid, ent in self.entities.items():
                    self._conn.execute(
                        "INSERT INTO kg_entities(eid,kind,attrs,ts) VALUES(?,?,?,?)",
                        (eid, ent["kind"], json.dumps(ent.get("attrs", {}), ensure_ascii=False),
                         ent.get("ts", time.time())))
                for r in self.relations:
                    self._conn.execute(
                        "INSERT INTO kg_relations(src,dst,rel,weight,valid_from,valid_to,evidence)"
                        " VALUES(?,?,?,?,?,?,?)",
                        (r["src"], r["dst"], r["rel"], r["weight"], r["valid_from"],
                         r["valid_to"], json.dumps(r.get("evidence", []), ensure_ascii=False)))
            return len(self.relations)
        except Exception as e:  # noqa: BLE001
            log.warning("KG 持久化失败: %s", e)
            return 0

    # ---------- 实体 ----------
    def add_entity(self, entity_id: str, kind: str = "stock",
                   attrs: dict | None = None, ts: float | None = None) -> dict:
        with self._lock:
            ent = self.entities.get(entity_id) or {
                "id": entity_id, "kind": kind, "attrs": {}, "ts": 0.0, "version": 0}
            ent["attrs"] = {**(ent.get("attrs") or {}), **(attrs or {})}
            ent["ts"] = ts or time.time()
            ent["version"] += 1
            self.entities[entity_id] = ent
            return ent

    def upsert(self, entity_id: str, attrs: dict | None = None) -> dict:
        return self.add_entity(entity_id, attrs=attrs)

    def get(self, entity_id: str) -> dict | None:
        return self.entities.get(entity_id)

    def has(self, entity_id: str) -> bool:
        return entity_id in self.entities

    # ---------- 关系（时序） ----------
    def add_relation(self, src: str, dst: str, rel: str, weight: float = 1.0,
                     valid_from: float | None = None, valid_to: float | None = None,
                     evidence: list | None = None, merge: bool = True) -> dict:
        now = time.time()
        rel_obj = {
            "src": src, "dst": dst, "rel": rel, "weight": float(weight),
            "valid_from": valid_from if valid_from is not None else now,
            "valid_to": valid_to, "evidence": evidence or [],
        }
        with self._lock:
            if merge:
                for r in self.relations:
                    if r["src"] == src and r["dst"] == dst and r["rel"] == rel:
                        # 更新权重（时间衰减叠加），延长有效期
                        r["weight"] = min(1.0, r["weight"] * 0.8 + rel_obj["weight"] * 0.6)
                        r["valid_to"] = rel_obj["valid_to"]
                        r["valid_from"] = min(r["valid_from"], rel_obj["valid_from"])
                        r["evidence"] = list(dict.fromkeys(r["evidence"] + rel_obj["evidence"]))[-10:]
                        return r
            self._seq += 1
            rel_obj["seq"] = self._seq
            self.relations.append(rel_obj)
            return rel_obj

    # ---------- 演化（新事件驱动） ----------
    def evolve(self, events: list[dict], now: float | None = None) -> int:
        """按事件流演化图谱：时间窗衰减权重、过期关系摘除、新增关系写入。

        events: [{src,dst,rel,weight,ts,evidence}]
        返回处理的（新增+更新）关系数。
        """
        now = now or time.time()
        changed = 0
        for ev in events:
            src, dst, rel = ev.get("src"), ev.get("dst"), ev.get("rel")
            if not (src and dst and rel):
                continue
            ts = ev.get("ts") or now
            w = float(ev.get("weight", 1.0))
            self.add_relation(src, dst, rel, weight=w, valid_from=ts,
                              evidence=ev.get("evidence"))
            self.add_entity(src, attrs={"last_event": ts})
            self.add_entity(dst, attrs={"last_event": ts})
            changed += 1
        self.decay(now)
        return changed

    def decay(self, now: float | None = None) -> int:
        """时间衰减：按半衰期降低旧关系权重；权重过低 → 摘除。"""
        now = now or time.time()
        half_life = self.decay_half_life_days * 86400
        removed = 0
        with self._lock:
            keep: list[dict] = []
            for r in self.relations:
                age = now - (r.get("valid_from") or now)
                if age > 0 and half_life > 0:
                    r["weight"] = r["weight"] * (0.5 ** (age / half_life))
                if r.get("valid_to") and now > r["valid_to"]:
                    removed += 1
                    continue  # 过期关系摘除
                if r["weight"] < 0.05:
                    removed += 1
                    continue
                keep.append(r)
            self.relations = keep
        return removed

    # ---------- 查询 ----------
    def active_relations(self, entity_id: str, now: float | None = None) -> list[dict]:
        now = now or time.time()
        return [r for r in self.relations
                if (r["src"] == entity_id or r["dst"] == entity_id)
                and (not r.get("valid_to") or now <= r["valid_to"])]

    def query_entity_relations(self, entity_id: str, depth: int = 2) -> dict:
        """广度优先遍历（含有效区间过滤），返回 {nodes, edges}。"""
        now = time.time()
        nodes: dict[str, dict] = {entity_id: {"entity": entity_id,
                                              "kind": self.entities.get(entity_id, {}).get("kind", "")}}
        edges: list[dict] = []
        frontier = [entity_id]
        for _ in range(max(1, depth)):
            nxt: list[str] = []
            for cur in frontier:
                for r in self.active_relations(cur, now):
                    other = r["dst"] if r["src"] == cur else r["src"]
                    if other not in nodes:
                        nodes[other] = {"entity": other,
                                        "kind": self.entities.get(other, {}).get("kind", "")}
                        nxt.append(other)
                    edges.append({"src": r["src"], "dst": r["dst"], "rel": r["rel"],
                                  "weight": round(r["weight"], 3)})
            frontier = nxt
            if not frontier:
                break
        return {"nodes": list(nodes.values()), "edges": edges}

    def chain(self, src: str, dst: str, max_len: int = 4) -> list[list[str]]:
        """查找 src→dst 的简单影响链（DFS，有向沿 src→dst 方向优先）。"""
        paths: list[list[str]] = []
        visited: set[str] = set()

        def dfs(cur: str, path: list[str]):
            if len(path) > max_len:
                return
            if cur == dst:
                paths.append(list(path))
                return
            for r in self.active_relations(cur):
                nxt = r["dst"]
                if nxt in visited:
                    continue
                visited.add(nxt)
                dfs(nxt, path + [nxt])
                visited.discard(nxt)

        visited.add(src)
        dfs(src, [src])
        return paths[:5]

    def stats(self) -> dict:
        return {"entities": len(self.entities), "relations": len(self.relations)}

    def clear(self) -> None:
        with self._lock:
            self.entities.clear()
            self.relations.clear()


# 模块级默认图谱（内存模式；上层可替换为持久化实例）
_default_kg = DynamicKG()


def default_kg() -> DynamicKG:
    return _default_kg


if __name__ == "__main__":
    kg = DynamicKG()
    kg.add_entity("SH600519", "stock", {"name": "贵州茅台"})
    kg.add_entity("IND:白酒", "industry")
    kg.add_entity("EV:涨价", "event")
    kg.add_relation("SH600519", "IND:白酒", "belongs_to", weight=1.0)
    kg.add_relation("EV:涨价", "IND:白酒", "impacted_by", weight=0.9)
    kg.add_relation("SH600519", "EV:涨价", "affected_by", weight=0.7)
    kg.evolve([{"src": "EV:涨价", "dst": "SH600519", "rel": "price_impact",
                "weight": 0.95, "ts": time.time(), "evidence": ["提价公告"]}])
    rel = kg.query_entity_relations("SH600519", depth=2)
    assert any(n["entity"] == "IND:白酒" for n in rel["nodes"])
    assert any(p == ["SH600519", "EV:涨价"] for p in kg.chain("SH600519", "EV:涨价"))
    ner = financial_ner("贵州茅台属于白酒板块，股价上涨")
    assert any(e["entity_id"] == "SH600519" for e in ner)
    assert any(e["entity_id"] == "IND:白酒" for e in ner)
    removed = kg.decay(now=time.time() + 400 * 86400)
    assert kg.stats()["relations"] < 4 or removed > 0
    print(f"PASS dynamic_kg 自测 stats={kg.stats()}")
