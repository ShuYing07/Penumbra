# -*- coding: utf-8 -*-
"""模块七 · 金融知识图谱事件传导链测试。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("STOCKAI_MOCK", "1")

import uuid

from memory.graph_memory import (add_entity, add_relation, query_event_chain,
                                 seed_demo, stats)

PASS = 0


def ok(name: str):
    global PASS
    PASS += 1
    print(f"[ok] {name}")


def test_seed_demo_event_chain():
    seed_demo()  # 幂等
    r = query_event_chain("600519", depth=3)
    assert r["root"] == "600519"
    assert r["chains"], "应从茅台出发找到事件传导链"
    event_names = {e["entity"] for e in r["events"]}
    assert "行业整顿" in event_names  # 茅台直接 affected_by 行业整顿
    all_rels = {rel for c in r["chains"] for rel in c["rels"]}
    assert "affected_by" in all_rels
    # 行业级事件链：从行业实体出发应看到两个行业事件
    r2 = query_event_chain("白酒", depth=2)
    ev2 = {e["entity"] for e in r2["events"]}
    assert "行业整顿" in ev2 and "需求复苏" in ev2
    ok("事件传导链：个股→直接事件；行业→全部相关事件")


def test_event_chain_isolated_entity():
    uid = uuid.uuid4().hex[:6]
    add_entity(uid, "stock", {})
    r = query_event_chain(uid, depth=2)
    assert r["root"] == uid
    assert r["chains"] == [] and r["events"] == []
    ok("孤立实体无事件链（不报错）")


def test_depth_bound():
    # 链长度受 depth 限制
    r = query_event_chain("600519", depth=1)
    for c in r["chains"]:
        assert len(c["path"]) <= 2  # root + 1 hop
    ok("传导链深度受 depth 约束")


def test_graph_stats_integrity():
    s = stats()
    assert s["nodes"] >= 5 and s["edges"] >= 4
    ok("图谱统计口径正常")


if __name__ == "__main__":
    test_seed_demo_event_chain()
    test_event_chain_isolated_entity()
    test_depth_bound()
    test_graph_stats_integrity()
    print(f"\nALL PASS ({PASS})")
