# -*- coding: utf-8 -*-
"""事件增强知识图谱：从新闻抽取实体和事件关系。"""
from __future__ import annotations

import logging
import re

log = logging.getLogger("stockai.kg")

# 事件类型关键词
_EVENT_KEYWORDS = {
    "业绩预增": ["业绩预增", "净利润增长", "营收增长", "超预期"],
    "业绩预减": ["业绩预减", "净利润下滑", "营收下降", "不及预期"],
    "股东减持": ["股东减持", "减持计划", "大宗交易减持"],
    "股东增持": ["股东增持", "增持计划", "回购股份"],
    "政策补贴": ["补贴", "政策支持", "税收优惠", "产业政策"],
    "产品发布": ["新品发布", "量产", "投产", "首发"],
    "战略合作": ["战略合作", "签约", "合作协议"],
    "风险事件": ["立案调查", "处罚", "违规", "诉讼"],
}


def extract_events(news_text: str) -> list[dict]:
    """从新闻文本中抽取事件类型。"""
    events = []
    for event_type, keywords in _EVENT_KEYWORDS.items():
        for kw in keywords:
            if kw in news_text:
                events.append({"type": event_type, "keyword": kw})
                break
    return events


def query_event_chain(event_type: str, depth: int = 2) -> list[str]:
    """返回事件的传导链（简化版，基于规则）。"""
    chains = {
        "政策补贴": ["政策补贴 → 行业成本下降 → 相关企业利润提升"],
        "业绩预增": ["业绩预增 → 市场预期上修 → 股价正向反应"],
        "股东减持": ["股东减持 → 市场供给增加 → 短期股价压力"],
        "产品发布": ["产品发布 → 营收预期增加 → 估值修复"],
    }
    return chains.get(event_type, ["（暂无传导链数据）"])


def build_entity_graph(news_list: list[dict]) -> dict:
    """从新闻列表构建简化实体关系图。"""
    entities = set()
    relations = []
    for n in news_list:
        title = n.get("title", "")
        events = extract_events(title)
        for ev in events:
            entities.add(ev["type"])
            relations.append({"from": "市场", "to": ev["type"], "via": title[:50]})
    return {"entities": list(entities), "relations": relations}
