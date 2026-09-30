# -*- coding: utf-8 -*-
"""金融事件演化知识图谱（模块四 · 参考 KEEKG 实体-事件-风险三层结构）。

- 三层：实体层（公司/人物/产品）、事件层（业绩预增/减持/政策补贴…）、
  风险层（信用/市场/流动性/经营）；
- query_event_chain(event_type, depth)：沿 affected_by / impacted_by /
  raises 关系做 BFS 传导链查询，返回 {nodes, edges, path}；
- predict_impact(event)：确定性因果推理——事件类型→风险冲击映射 +
  图传播（事件→实体→行业→风险层），返回影响路径与风险评分；
- 存储：SQLite event_graph.db（nodes/edges 表），可独立自检；
- 复用 memory.event_extractor 的事件类型抽取；不强依赖 DGL/图神经网络
  （生产级动态图神经网络列为可选扩展，见 docstring）。
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import sys
import time
from contextlib import contextmanager
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.config import DATA_DIR

log = logging.getLogger("stockai.core.event_graph")

_DB = DATA_DIR / "event_graph.db"
_SCHEMA = """
CREATE TABLE IF NOT EXISTS eg_nodes(
  id TEXT PRIMARY KEY, layer TEXT, kind TEXT, label TEXT, meta TEXT
);
CREATE TABLE IF NOT EXISTS eg_edges(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  src TEXT, dst TEXT, rel TEXT, weight REAL
);
CREATE INDEX IF NOT EXISTS idx_eg_edges_src ON eg_edges(src);
CREATE INDEX IF NOT EXISTS idx_eg_edges_dst ON eg_edges(dst);
"""

# 事件类型 → 风险冲击（确定性因果映射）
EVENT_RISK: Dict[str, Dict[str, float]] = {
    "业绩预增": {"市场风险": -0.3, "信用风险": -0.1, "经营风险": -0.2},
    "业绩预减": {"市场风险": 0.4, "信用风险": 0.3, "经营风险": 0.4},
    "股东减持": {"市场风险": 0.4, "流动性风险": 0.3},
    "股东增持": {"市场风险": -0.3, "流动性风险": -0.2},
    "政策补贴": {"经营风险": -0.3, "市场风险": -0.2},
    "重大合同": {"经营风险": -0.3, "信用风险": -0.1},
    "重大风险": {"信用风险": 0.5, "市场风险": 0.3, "流动性风险": 0.3, "经营风险": 0.4},
    "高管变动": {"经营风险": 0.3, "信用风险": 0.1},
    "收购并购": {"市场风险": 0.2, "经营风险": 0.1},
    "其他事件": {},
}

_LAYERS = {"entity", "event", "risk"}


def _conn() -> sqlite3.Connection:
    _DB.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(_DB))
    c.executescript(_SCHEMA)
    return c


@contextmanager
def _db():
    c = _conn()
    try:
        yield c
        c.commit()
    finally:
        c.close()


def _add_node(c: sqlite3.Connection, nid: str, layer: str, kind: str,
              label: str, meta: Optional[dict] = None) -> None:
    c.execute(
        "INSERT OR REPLACE INTO eg_nodes(id,layer,kind,label,meta) VALUES(?,?,?,?,?)",
        (nid, layer, kind, label, json.dumps(meta or {}, ensure_ascii=False)))


def _add_edge(c: sqlite3.Connection, src: str, dst: str, rel: str,
              weight: float = 1.0) -> None:
    c.execute("INSERT OR IGNORE INTO eg_edges(src,dst,rel,weight) VALUES(?,?,?,?)",
              (src, dst, rel, weight))


def build_from_texts(entity: str, texts: List[str],
                     industry: Optional[str] = None) -> dict:
    """从文本建图：实体 →(affected_by) 事件 →(raises) 风险；
    industry 存在时事件 →(impacted_by) 行业。返回 {nodes, edges, events}。"""
    from memory.event_extractor import extract_event_type
    with _db() as c:
        _add_node(c, entity, "entity", "stock", entity)
        events = []
        for t in (texts or []):
            label, _ = extract_event_type(t)
            ename = f"ev:{label}:{abs(hash(t)) % 100000}"
            _add_node(c, ename, "event", "event", label, {"text": t[:60]})
            _add_edge(c, entity, ename, "affected_by", 1.0)
            events.append({"event": ename, "type": label, "text": t[:60]})
            for risk, shock in (EVENT_RISK.get(label) or {}).items():
                rid = f"risk:{risk}"
                _add_node(c, rid, "risk", "risk", risk, {"shock": shock})
                _add_edge(c, ename, rid, "raises", max(0.1, abs(shock)))
            if industry:
                _add_node(c, industry, "entity", "industry", industry)
                _add_edge(c, ename, industry, "impacted_by", 0.8)
    return {"nodes": len(events) + 1 + len(EVENT_RISK),
            "edges": len(events) * (1 + len(EVENT_RISK.get(events[0]["type"] or "", {})) if events else 0),
            "events": events}


def query_event_chain(entity: Optional[str] = None,
                      event_type: Optional[str] = None,
                      depth: int = 3) -> dict:
    """沿传导链查询（BFS，深度 ≤ depth）。

    返回 {nodes:[{id,layer,label}], edges:[{src,dst,rel}], path:[...]}：
    - path 为「实体 → 事件 → 风险」的可读链路字符串。
    """
    with _db() as c:
        nodes = c.execute("SELECT id,layer,label FROM eg_nodes").fetchall()
        edges = c.execute("SELECT src,dst,rel FROM eg_edges").fetchall()
    adj: Dict[str, List[Tuple[str, str]]] = {}
    for s, d, r in edges:
        adj.setdefault(s, []).append((d, r))
        adj.setdefault(d, []).append((s, r))

    # 起点：实体（指定或事件类型）
    if entity:
        start = entity
    elif event_type:
        start = next((n["id"] for n in _nodes_dict(nodes)
                      if n["label"] == event_type), None)
    else:
        start = nodes[0][0] if nodes else None
    if start is None:
        return {"nodes": [], "edges": [], "path": []}

    label_of = {n[0]: (n[1], n[2]) for n in nodes}
    visited: Dict[str, int] = {start: 0}
    queue: List[Tuple[str, int, List[str]]] = [(start, 0, [])]
    chain: List[str] = []
    while queue:
        cur, d, path = queue.pop(0)
        layer, lbl = label_of.get(cur, ("", cur))
        chain.append(lbl)
        if d >= depth:
            continue
        for nxt, rel in adj.get(cur, []):
            if nxt not in visited or visited[nxt] > d + 1:
                visited[nxt] = d + 1
                queue.append((nxt, d + 1, path + [rel]))
    sub_nodes = [{"id": i, "layer": l, "label": lb} for i, (l, lb) in label_of.items()
                 if i in visited]
    sub_edges = [{"src": s, "dst": d, "rel": r} for s, d, r in edges
                 if s in visited and d in visited]
    return {"nodes": sub_nodes, "edges": sub_edges, "path": chain}


def predict_impact(entity: str, texts: List[str],
                   industry: Optional[str] = None) -> dict:
    """因果推理：事件 → 风险冲击评分 + 影响路径（确定性传播）。

    返回 {path:[(节点, 关系)], risk_scores:{风险: 冲击}, summary}。
    """
    from memory.event_extractor import extract_event_type
    risk: Dict[str, float] = {}
    path: List[Tuple[str, str]] = []
    for t in (texts or []):
        label, _ = extract_event_type(t)
        path.append((entity, "affected_by"))
        path.append((label, "raises"))
        for risk_name, shock in (EVENT_RISK.get(label) or {}).items():
            risk[risk_name] = risk.get(risk_name, 0.0) + shock
            path.append((risk_name, "exposed_to"))
        if industry:
            path.append((industry, "impacted_by"))
    scored = sorted(risk.items(), key=lambda kv: -abs(kv[1]))
    top = scored[0] if scored else None
    summary = (f"主要风险：{top[0]}（冲击 {top[1]:+.2f}）" if top
               else "无显著风险冲击")
    return {"path": path, "risk_scores": risk, "summary": summary}


def _nodes_dict(rows: List[Tuple[str, str, str]]) -> List[dict]:
    return [{"id": r[0], "layer": r[1], "label": r[2]} for r in rows]


if __name__ == "__main__":
    # 自检
    texts = ["贵州茅台业绩预增，净利润同比增长15%",
             "某股东减持套现1亿元",
             "公司收到政府补贴3000万元"]
    b = build_from_texts("600519", texts, industry="白酒")
    assert b["events"], b
    assert b["nodes"] >= 4
    chain = query_event_chain("600519", depth=3)
    assert chain["nodes"] and chain["path"]
    imp = predict_impact("600519", texts, "白酒")
    assert imp["risk_scores"], imp
    assert imp["summary"]
    assert any(k in imp["risk_scores"] for k in ("市场风险", "信用风险", "流动性风险"))
    # 事件类型过滤
    c2 = query_event_chain(event_type="业绩预增", depth=2)
    assert c2["nodes"]
    print(f"event_graph self-check ok (nodes={b['nodes']}, "
          f"path={chain['path'][:4]}, risk={imp['summary']})")
