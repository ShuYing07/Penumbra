# -*- coding: utf-8 -*-
"""宏观市场概览：主要宽基指数实时点位/涨跌（新浪实时行情，轻量稳定）。"""
from __future__ import annotations

import logging

from core.config import domestic_network

log = logging.getLogger("stockai.data.overview")

# 新浪 s_ 指数：(代码, 名称)
_INDICES = [
    ("s_sh000001", "上证指数"),
    ("s_sz399001", "深证成指"),
    ("s_sz399006", "创业板指"),
    ("s_sh000300", "沪深300"),
    ("s_sh000905", "中证500"),
    ("s_sh000016", "上证50"),
]


def list_market_indices() -> list[dict]:
    """返回 [{code,name,price,chg_pct}]；失败返回空列表，绝不抛到 UI。"""
    codes = ",".join(c for c, _ in _INDICES)
    url = f"https://hq.sinajs.cn/list={codes}"
    try:
        with domestic_network():
            import requests
            r = requests.get(url, headers={"Referer": "https://finance.sina.com.cn"}, timeout=8)
            r.encoding = "gbk"
            txt = r.text
    except Exception as e:  # noqa: BLE001
        log.warning("指数概览拉取失败：%s", e)
        return []

    name_map = dict(_INDICES)
    out = []
    for line in txt.splitlines():
        if "=" not in line:
            continue
        var, val = line.split("=", 1)
        code = var.strip().replace("var hq_str_", "")
        # s_sh000001 → sh000001 与 name_map 对齐
        key = "s_" + code.lstrip("s_") if not code.startswith("s_") else code
        parts = val.strip().strip('";').split(",")
        if len(parts) < 4:
            continue
        try:
            name = name_map.get(code, parts[0] or code)
            price = float(parts[1])
            chg_pct = float(parts[3])
            out.append({"code": code, "name": name,
                        "price": round(price, 2), "chg_pct": round(chg_pct, 2)})
        except (ValueError, TypeError):
            continue
    return out
