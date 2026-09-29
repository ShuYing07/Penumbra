# -*- coding: utf-8 -*-
"""自然语言 → 结构化筛选条件（离线规则解析，供 AgentCore 调用）。

参考 iFinD 智能选股 / 九章 ALGOR 智能问财：用户说
"市盈率低于15、股息率高于3%的银行股" → 解析为结构化条件 dict。
本模块为纯规则实现（确定性、离线可用），不依赖 LLM。
"""
from __future__ import annotations

import re
from typing import Dict, Optional

_MARKETS = {"A股": "A股", "港股": "港股", "美股": "美股", "指数": "指数",
            "a股": "A股", "沪深": "A股", "a": "A股", "hk": "港股",
            "us": "美股", "美股": "美股"}
_BOARDS = ["银行", "白酒", "医药", "半导体", "芯片", "新能源", "光伏", "军工",
           "消费", "食品", "地产", "券商", "保险", "汽车", "家电", "计算机",
           "通信", "传媒", "钢铁", "有色", "化工", "机械", "电力", "公用事业",
           "煤炭", "石油", "农业", "纺织", "环保", "港口", "航空", "旅游"]


def parse_nl_to_conditions(text: str) -> Dict[str, Optional[object]]:
    """解析自然语言筛选描述 → {market, board, price_min, price_max, chg_min, chg_max}。"""
    low = text.lower()
    conds: Dict[str, Optional[object]] = {}

    # 市场
    for kw, val in _MARKETS.items():
        if kw in text:
            conds["market"] = val
            break

    # 板块/行业
    for b in _BOARDS:
        if b in text:
            conds["board"] = b
            break

    # 价格区间："价格低于 50 / 高于 100 / 30-80 元"
    m = re.search(r"(?:价格|股价)[低于不超过小于]+\s*([\d.]+)", low)
    if m:
        conds["price_max"] = float(m.group(1))
    m = re.search(r"(?:价格|股价)[高于超过大于]+\s*([\d.]+)", low)
    if m:
        conds["price_min"] = float(m.group(1))
    m = re.search(r"价格\s*([\d.]+)\s*[-~到]\s*([\d.]+)", low)
    if m:
        conds["price_min"], conds["price_max"] = float(m.group(1)), float(m.group(2))

    # 涨跌幅："涨跌幅低于 -2% / 涨幅大于 5%"
    m = re.search(r"涨跌幅?[低于不超过小于]+\s*([-]?[\d.]+)%?", low)
    if m:
        conds["chg_max"] = float(m.group(1))
    m = re.search(r"(?:涨跌幅|涨幅|跌幅)[高于超过大于]+\s*([-]?[\d.]+)%?", low)
    if m:
        conds["chg_min"] = float(m.group(1))

    return conds
