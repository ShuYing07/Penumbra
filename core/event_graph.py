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
from datetime import datetime
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


# ---------------------------------------------------------------------------
# 模块五增强：FinKG-News 事件锚定 + HERMES 时序实体识别与动态演化
# ---------------------------------------------------------------------------
# 新增命名空间表，不改动既有 nodes/edges schema，保证已有自检与 UI 不受影响。
_SCHEMA_EXT = """
CREATE TABLE IF NOT EXISTS eg_anchor(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  entity TEXT, etype TEXT, adate TEXT, entities TEXT,
  sentiment REAL, source TEXT, text TEXT, created TEXT
);
CREATE TABLE IF NOT EXISTS eg_tentity(
  name TEXT PRIMARY KEY, kind TEXT, first_seen TEXT, last_seen TEXT, mentions INTEGER
);
CREATE INDEX IF NOT EXISTS idx_eg_anchor_entity ON eg_anchor(entity);
CREATE INDEX IF NOT EXISTS idx_eg_anchor_date ON eg_anchor(adate);
"""

# 各类实体的正则（HERMES 风格规则 NER，best-effort）：
# - company：已知 A股公司名 / 1~6 个汉字 + 机构后缀词
# - person：职务/角色词（作为人物实体）
# - macro：宏观主体/指标关键词（本身即实体）
# - industry：行业关键词（本身即实体）
_ENTITY_PATTERNS = [
    ("company", r"[\u4e00-\u9fa5]{1,6}(?:公司|集团|股份|银行|证券|科技|医药|传媒|地产|控股)"),
    ("person", r"(?:董事长|总裁|CEO|创始人|实控人|总经理|董秘)"),
    ("macro", r"(?:央行|美联储|国务院|证监会|发改委|财政部|GDP|CPI|PPI|LPR|存款准备金|利率|汇率|货币政策)"),
    ("industry", r"(?:新能源|半导体|光伏|锂电池|人工智能|芯片|白酒|医药|房地产|券商|汽车|消费电子|军工|养殖)"),
]
# A股常见公司别名（无机构后缀时的精确匹配）
_KNOWN_COMPANIES = {
    "贵州茅台", "茅台", "五粮液", "宁德时代", "比亚迪", "中国平安", "平安银行",
    "招商银行", "工商银行", "建设银行", "农业银行", "隆基绿能", "京东方", "美的集团",
    "格力电器", "伊利股份", "海康威视", "立讯精密", "三一重工", "中信证券",
    "东方财富", "药明康德", "迈瑞医疗", "长江电力", "中国中车", "中芯国际",
}
_POS = ("增长", "预增", "增持", "利好", "签约", "中标", "补贴", "盈利", "回暖", "新高")
_NEG = ("预减", "减持", "暴雷", "亏损", "处罚", "诉讼", "下滑", "违约", "退市", "利空")


def _norm_date(s) -> str:
    import re as _re
    t = str(s or "")
    m = _re.search(r"(\d{4})[-/]?(\d{1,2})[-/]?(\d{1,2})", t)
    return f"{m.group(1)}{int(m.group(2)):02d}{int(m.group(3)):02d}" if m else ""


def recognize_entities(text: str) -> List[dict]:
    """HERMES 风格时序实体识别（规则 NER）：返回 [{name, kind}]。

    覆盖公司/人物/宏观主体/行业四类，供事件锚定到具体实体（FinKG-News）。
    """
    import re as _re
    out: List[dict] = []
    seen = set()
    # 1) 已知公司名（最长优先，避免"茅台"被"贵州茅台"拆开）
    for name in sorted(_KNOWN_COMPANIES, key=len, reverse=True):
        if name in text and name not in seen:
            seen.add(name)
            out.append({"name": name, "kind": "company"})
    # 2) 各类正则（跳过已匹配公司名的子串，如"茅台"被"贵州茅台"覆盖）
    for kind, pat in _ENTITY_PATTERNS:
        for m in _re.finditer(pat, text):
            name = m.group(0).strip()
            if not name or name in seen:
                continue
            if any(name in s for s in seen):
                continue
            seen.add(name)
            out.append({"name": name, "kind": kind})
    return out


def _sentiment(text: str) -> float:
    pos = sum(text.count(w) for w in _POS)
    neg = sum(text.count(w) for w in _NEG)
    return round((pos - neg) / max(1, pos + neg), 3)


def _record_entity(c, name: str, kind: str, as_of: str) -> None:
    row = c.execute("SELECT first_seen, mentions FROM eg_tentity WHERE name=?", (name,)).fetchone()
    if row is None:
        c.execute("INSERT INTO eg_tentity(name,kind,first_seen,last_seen,mentions) VALUES(?,?,?,?,1)",
                  (name, kind, as_of, as_of))
    else:
        c.execute("UPDATE eg_tentity SET last_seen=?, mentions=?, kind=? WHERE name=?",
                  (as_of, row[1] + 1, kind, name))


def anchor_event(entity: str, text: str, date: str | None = None,
                source: str = "") -> dict:
    """FinKG-News 风格事件锚定：把一条新闻锚定到 (日期, 实体, 情感, 来源)。

    返回锚定记录 {id, entity, etype, date, entities, sentiment, source, text}。
    """
    from memory.event_extractor import extract_event_type
    label, _ = extract_event_type(text)
    as_of = _norm_date(date or "")
    ents = recognize_entities(text)
    sent = _sentiment(text)
    with _db_ext() as c:
        c.executescript(_SCHEMA_EXT)
        cur = c.execute(
            "INSERT INTO eg_anchor(entity,etype,adate,entities,sentiment,source,text,created)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (entity, label, as_of, json.dumps(ents, ensure_ascii=False), sent, source,
             text[:200], datetime.now().isoformat(timespec="seconds")))
        aid = cur.lastrowid
        for e in ents:
            _record_entity(c, e["name"], e["kind"], as_of or "19700101")
    return {"id": aid, "entity": entity, "etype": label, "date": as_of,
            "entities": ents, "sentiment": sent, "source": source, "text": text[:200]}


def build_from_news_stream(entity: str, items: List[dict]) -> dict:
    """批量锚定新闻流（HERMES 动态演化输入）。

    items=[{text, date(可选), source(可选)}]。返回 {anchored, entities}。
    """
    anchored, names = 0, set()
    for it in (items or []):
        a = anchor_event(entity, it.get("text", ""), it.get("date"), it.get("source", ""))
        anchored += 1
        for e in a["entities"]:
            names.add(e["name"])
    return {"anchored": anchored, "entities": sorted(names)}


def evolve(entity: str, as_of: str, half_life_days: int = 30) -> dict:
    """HERMES 动态演化：按锚定事件日期对实体/事件做时间衰减权重。

    返回 {as_of, half_life_days, alive_entities, stale_entities, recent_events}：
    - alive：最近 half_life 内有提及的实体；
    - stale：超过 2×half_life 无提及的实体（知识演化淘汰）；
    - recent_events：as_of 前 half_life 内的锚定事件数。
    """
    ao = _norm_date(as_of) or ""
    with _db_ext() as c:
        c.executescript(_SCHEMA_EXT)
        rows = c.execute(
            "SELECT name, last_seen, mentions FROM eg_tentity WHERE name IN "
            "(SELECT DISTINCT json_extract(json_each.value, '$.name') FROM eg_anchor, "
            "json_each(eg_anchor.entities) WHERE eg_anchor.entity=?)",
            (entity,)).fetchall()
    alive, stale = [], []
    for name, last_seen, _m in rows:
        if not ao or not last_seen:
            alive.append(name); continue
        age = (int(ao) - int(last_seen)) if ao.isdigit() and last_seen.isdigit() else 9999
        (alive if age <= half_life_days else (stale if age > 2 * half_life_days else alive)).append(name)
    return {"as_of": ao, "half_life_days": half_life_days,
            "alive_entities": alive, "stale_entities": stale,
            "entity_count": len(rows)}


@contextmanager
def _db_ext():
    _DB.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(_DB))
    try:
        c.executescript(_SCHEMA_EXT)
        yield c
        c.commit()
    finally:
        c.close()


def query_anchored(entity: str, since: str | None = None,
                   sentiment_le: float | None = None) -> List[dict]:
    """查询某标的的锚定事件（可按日期下限 / 情感阈值过滤）。"""
    with _db_ext() as c:
        c.executescript(_SCHEMA_EXT)
        sql = "SELECT id, etype, adate, entities, sentiment, source, text FROM eg_anchor WHERE entity=?"
        args = [entity]
        if since:
            sql += " AND adate>=?"
            args.append(_norm_date(since))
        if sentiment_le is not None:
            sql += " AND sentiment<=?"
            args.append(sentiment_le)
        sql += " ORDER BY adate DESC, id DESC"
        rows = c.execute(sql, args).fetchall()
    return [{"id": r[0], "etype": r[1], "date": r[2],
             "entities": json.loads(r[3]) if r[3] else [], "sentiment": r[4],
             "source": r[5], "text": r[6]} for r in rows]


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
