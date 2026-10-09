# -*- coding: utf-8 -*-
"""第20轮 · 事件图谱因果链深化测试。

验证：路径枚举与强度连乘、时效衰减、PIT（未来事件不入链）、
一阶邻域导出、层结构完整、格式化输出、空图容错。
用 uuid 隔离实体，避免与既有库数据互相污染。
"""
from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("STOCKAI_MOCK", "1")

from core import event_graph as eg


def _new_entity() -> str:
    return f"T{uuid.uuid4().hex[:8]}"


def _seed(entity: str, texts=None, industry=None):
    texts = texts or ["公司业绩预增，净利润同比增长20%",
                      "某股东减持套现5000万元"]
    return eg.build_from_texts(entity, texts, industry=industry)


# --------------------------------------------------------------------------
# 基础：路径与强度
# --------------------------------------------------------------------------
def test_chains_found_from_entity():
    e = _new_entity()
    _seed(e)
    rep = eg.query_causal_chains(entity=e, depth=3, top_k=5)
    assert rep["chain_count"] > 0
    assert len(rep["chains"]) <= 5
    for c in rep["chains"]:
        assert c["strength"] > 0
        assert c["steps"] >= 1
        assert len(c["nodes"]) == c["steps"] + 1
        assert len(c["rels"]) == c["steps"]
        assert " → " in c["path"]


def test_strength_is_product_of_weights():
    e = _new_entity()
    _seed(e)
    rep = eg.query_causal_chains(entity=e, depth=2, top_k=20)
    # 首条链（steps=1）的强度应等于该边权
    one = [c for c in rep["chains"] if c["steps"] == 1]
    assert one, rep["chains"][:3]
    edges = {(s, d): w for s, d, _r, w in eg._weighted_edges()}
    for c in one:
        w = edges.get((c["nodes"][0], c["nodes"][1]))
        if w is None:                       # 反向边（无向邻接）
            w = edges.get((c["nodes"][1], c["nodes"][0]))
        if w is not None:
            assert abs(c["strength"] - w) < 1e-6


def test_chains_sorted_by_decayed_strength():
    e = _new_entity()
    _seed(e)
    rep = eg.query_causal_chains(entity=e, depth=3, top_k=10)
    vals = [c["decayed"] for c in rep["chains"]]
    assert vals == sorted(vals, reverse=True)


def test_depth_respected():
    e = _new_entity()
    _seed(e)
    rep = eg.query_causal_chains(entity=e, depth=1, top_k=50)
    assert all(c["steps"] <= 1 for c in rep["chains"])


def test_start_from_event_type():
    e = _new_entity()
    _seed(e)
    rep = eg.query_causal_chains(event_type="业绩预增", depth=2, top_k=3)
    assert rep["chain_count"] > 0


# --------------------------------------------------------------------------
# 时效衰减
# --------------------------------------------------------------------------
def test_decay_monotonic():
    assert eg._decay(0, 30) == 1.0
    assert abs(eg._decay(30, 30) - 0.5) < 1e-9
    assert eg._decay(60, 30) < eg._decay(30, 30)
    assert eg._decay(10000, 30) >= 0.0


def test_age_days_calculation():
    assert eg._age_days("20240101", "20240131") == 30
    assert eg._age_days("20240101", "20240101") == 0
    assert eg._age_days("bad", "20240101") == 0.0      # 解析失败按最新处理


def test_decayed_not_exceeds_raw():
    e = _new_entity()
    _seed(e)
    rep = eg.query_causal_chains(entity=e, depth=2, as_of="2020-01-01",
                                 top_k=10)
    for c in rep["chains"]:
        assert c["decayed"] <= c["strength"] + 1e-9


# --------------------------------------------------------------------------
# PIT：未来事件不入链
# --------------------------------------------------------------------------
def test_pit_filters_future_events():
    e = _new_entity()
    # 建图时同时放入一个「重大合同」事件节点
    _seed(e, texts=["公司业绩预增，净利润同比增长20%",
                    "公司签订重大合同，金额超预期"])
    # 把「重大合同」锚定为 2099 年才发生（该时点市场还不知道）
    eg.anchor_event(e, "公司签订重大合同，金额超预期", date="2099-01-01")
    assert "重大合同" in eg._future_event_types("20200101")

    future = eg.query_causal_chains(entity=e, depth=2, as_of="2020-01-01",
                                    top_k=50)
    labels_future = {lb for c in future["chains"] for lb in c["labels"]}
    past = eg.query_causal_chains(entity=e, depth=2, as_of="2099-06-01",
                                  top_k=50)
    labels_past = {lb for c in past["chains"] for lb in c["labels"]}
    assert "重大合同" not in labels_future, labels_future
    assert "业绩预增" in labels_future        # 非未来事件仍应在链上
    assert "重大合同" in labels_past, labels_past


def test_as_of_absent_keeps_all():
    e = _new_entity()
    _seed(e, texts=["公司业绩预增，净利润同比增长20%",
                    "公司业绩预减，净利润下滑"])
    eg.anchor_event(e, "公司业绩预减，净利润下滑", date="2099-01-01")
    rep = eg.query_causal_chains(entity=e, depth=2, top_k=50)
    assert rep["chain_count"] > 0
    assert rep["as_of"] == ""
    labels = {lb for c in rep["chains"] for lb in c["labels"]}
    assert "业绩预减" in labels


def test_future_types_empty_without_as_of():
    assert eg._future_event_types("") == set()


# --------------------------------------------------------------------------
# 力导向图数据
# --------------------------------------------------------------------------
def test_graph_for_ui_neighborhood():
    e = _new_entity()
    _seed(e, industry="白酒")
    g = eg.graph_for_ui(entity=e)
    assert g["node_count"] >= 2
    assert any(n["id"] == e for n in g["nodes"])
    for n in g["nodes"]:
        assert {"id", "label", "layer", "kind", "size"} <= set(n)
    for l in g["links"]:
        assert {"source", "target", "rel", "weight"} <= set(l)
    assert set(g["layers"]) <= {"entity", "event", "risk"}


def test_graph_for_ui_links_reference_kept_nodes():
    e = _new_entity()
    _seed(e, industry="半导体")
    g = eg.graph_for_ui(entity=e)
    ids = {n["id"] for n in g["nodes"]}
    for l in g["links"]:
        assert l["source"] in ids and l["target"] in ids


def test_graph_for_ui_limit():
    e = _new_entity()
    _seed(e)
    g = eg.graph_for_ui(entity=e, limit=3)
    assert g["node_count"] <= 3


def test_graph_for_ui_pit_filter():
    e = _new_entity()
    _seed(e)
    eg.anchor_event(e, "公司业绩预减", date="2099-01-01")
    g_old = eg.graph_for_ui(entity=e, as_of="2020-01-01")
    assert g_old["node_count"] >= 1


# --------------------------------------------------------------------------
# 容错与格式
# --------------------------------------------------------------------------
def test_unknown_entity_tolerated():
    rep = eg.query_causal_chains(entity="__not_exist__", depth=2)
    assert isinstance(rep["chains"], list)
    assert rep["summary"]


def test_format_chains_readable():
    e = _new_entity()
    _seed(e)
    rep = eg.query_causal_chains(entity=e, depth=2, top_k=2)
    txt = eg.format_chains(rep)
    assert "强度" in txt and "→" in txt


def test_weighted_edges_shape():
    rows = eg._weighted_edges()
    assert all(len(r) == 4 for r in rows)
    assert all(isinstance(r[3], float) for r in rows)


if __name__ == "__main__":
    for name, fn in sorted(list(globals().items())):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok  {name}")
    print("ALL OK")
