# -*- coding: utf-8 -*-
"""券商官方开户链接配置。所有链接均指向券商官方域名。"""
from __future__ import annotations


BROKER_OPEN_LINKS: dict[str, dict] = {
    "华泰证券": {"name": "华泰证券", "url": "https://www.htsc.com.cn/", "note": "官方首页"},
    "中信证券": {"name": "中信证券", "url": "https://www.citics.com/", "note": "官方首页"},
    "招商证券": {"name": "招商证券", "url": "https://www.cmschina.com/", "note": "官方首页"},
    "国泰君安": {"name": "国泰君安", "url": "https://www.gtja.com/", "note": "官方首页"},
    "海通证券": {"name": "海通证券", "url": "https://www.htsec.com/", "note": "官方首页"},
    "广发证券": {"name": "广发证券", "url": "https://www.gf.com.cn/", "note": "官方首页"},
    "中信建投": {"name": "中信建投", "url": "https://www.csc108.com/", "note": "官方首页"},
    "银河证券": {"name": "银河证券", "url": "https://www.chinastock.com.cn/", "note": "官方首页"},
    "申万宏源": {"name": "申万宏源", "url": "https://www.swhysc.com/", "note": "官方首页"},
    "东方财富": {"name": "东方财富", "url": "https://www.eastmoney.com/", "note": "官方首页"},
}


def list_brokers() -> list[str]:
    """返回所有券商名称列表。"""
    return list(BROKER_OPEN_LINKS.keys())


def get_broker_link(name: str) -> dict | None:
    """按名称返回券商链接，找不到返回None。"""
    return BROKER_OPEN_LINKS.get(name)


if __name__ == "__main__":
    print(list_brokers())
    print(get_broker_link("华泰证券"))
