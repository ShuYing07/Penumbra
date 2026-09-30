# -*- coding: utf-8 -*-
"""事件抽取器（模块五 · 参考 FinKario / FinKG-News）。

从新闻标题 / 公告标题中抽取事件类型（业绩预增、股东减持、政策补贴、
重大合同、风险提示等），并把事件与目标实体（股票代码/公司名）建立传导
链入库（memory.graph_memory：事件 → 实体 affected_by / impacted_by）。

- extract_event_type(text)：纯函数，返回 (event_label, event_name)；
- link_event_to_entity(entity, text)：抽取并入库，返回已建立的关系数；
- 幂等设计：同一事件名重复入库不重复建链（INSERT OR IGNORE 语义）。
"""
from __future__ import annotations

import logging
import re

log = logging.getLogger("stockai.memory.event")

# 事件类型 → 关键词表（顺序即优先级）
_EVENT_RULES: list[tuple[str, list[str]]] = [
    ("业绩预增", ["业绩预增", "净利润增长", "营收增长", "预盈", "扭亏为盈", "大幅增长",
                "同比增长", "业绩超预期"]),
    ("业绩预减", ["业绩预减", "净利润下滑", "预亏", "亏损扩大", "业绩下滑", "同比下降"]),
    ("股东减持", ["减持", "股东减持", "套现", "清仓式减持"]),
    ("股东增持", ["增持", "股东增持", "回购", "举牌"]),
    ("政策补贴", ["补贴", "政策利好", "产业政策", "扶持", "专项资金", "税收优惠", "降准", "降息"]),
    ("重大合同", ["中标", "重大合同", "签署协议", "战略合作", "大单", "订单"]),
    ("重大风险", ["风险提示", "违规", "处罚", "立案", "调查", "诉讼", "担保", "商誉减值",
                "债务违约", "退市风险"]),
    ("高管变动", ["董事长辞职", "CEO离职", "高管离职", "人事变动", "换届"]),
    ("收购并购", ["收购", "并购", "重组", "资产注入", "股权转让"]),
    ("其他事件", []),
]

# 事件名规范化：去掉数字/空格，最长 24 字
def _event_name(label: str, text: str) -> str:
    t = re.sub(r"\s+", "", text or "")[:18]
    return f"{label}:{t}" if t else label


def extract_event_type(text: str) -> tuple[str, str]:
    """从文本提取事件类型。返回 (label, event_name)。"""
    if not text:
        return ("其他事件", "其他事件")
    for label, kws in _EVENT_RULES:
        if any(k in text for k in kws):
            return (label, _event_name(label, text))
    return ("其他事件", _event_name("其他事件", text))


def link_event_to_entity(entity: str, text: str) -> dict:
    """抽取事件并把传导链写入知识图谱。

    返回 {event, event_type, relations, linked}：
    - 建立 实体 → affected_by → 事件（实体受事件影响）；
    - 事件 → impacted_by → 实体所在行业（若有 industry 参数，见 link_events_batch）。
    """
    if not text:
        return {"event": None, "event_type": None, "relations": 0, "linked": False}
    label, ename = extract_event_type(text)
    try:
        from memory.graph_memory import add_entity, add_relation
        add_entity(ename, "event", {"type": label})
        add_entity(entity, "stock", {"name": entity})
        add_relation(entity, ename, "affected_by", weight=1.0)
        return {"event": ename, "event_type": label, "relations": 1, "linked": True}
    except Exception as e:  # noqa: BLE001
        log.warning("事件入库失败：%s", e)
        return {"event": None, "event_type": label, "relations": 0, "linked": False}


def link_events_batch(entity: str, texts: list[str],
                      industry: str | None = None) -> dict:
    """批量抽取并建立传导链。industry 非空时，事件同时影响行业实体。

    返回 {events: [...], total_relations, per_event: [...]}。
    """
    out: list[dict] = []
    rels = 0
    for t in (texts or []):
        r = link_event_to_entity(entity, t)
        rels += r["relations"]
        if r["linked"] and industry:
            try:
                from memory.graph_memory import add_entity, add_relation
                add_entity(industry, "industry", {})
                add_relation(r["event"], industry, "impacted_by", weight=0.8)
                rels += 1
            except Exception:  # noqa: BLE001
                pass
        if r["linked"]:
            out.append(r)
    return {"events": out, "total_relations": rels,
            "per_event": [{"event": r["event"], "type": r["event_type"]}
                          for r in out]}


if __name__ == "__main__":
    # 自检
    assert extract_event_type("贵州茅台业绩预增，净利润同比增长15%")[0] == "业绩预增"
    assert extract_event_type("某股东减持套现")[0] == "股东减持"
    assert extract_event_type("公司收到政府补贴3000万元")[0] == "政策补贴"
    assert extract_event_type("日常经营正常")[0] == "其他事件"
    print("event_extractor self-check ok")
