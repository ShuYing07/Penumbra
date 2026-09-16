# -*- coding: utf-8 -*-
"""全局/宏观新闻：财联社电报（中文）+ Google News RSS（英文，按关键词）。"""
from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

import requests

from core.config import domestic_network, foreign_network

log = logging.getLogger("stockai.news")


def cls_global(limit: int = 20) -> list[dict]:
    """财联社全球电报（A 股全市场共用的宏观快讯）。"""
    import akshare as ak

    try:
        with domestic_network():
            df = ak.stock_info_global_cls()
    except Exception as e:  # noqa: BLE001
        log.warning("财联社快讯失败: %s", e)
        return []
    items = []
    for _, r in df.head(limit).iterrows():
        date = str(r.get("发布日期", "")).strip()
        tm = str(r.get("发布时间", "")).strip()
        title = str(r.get("标题", "")).strip()
        content = str(r.get("内容", "")).strip()
        items.append({
            "ticker": None,
            "title": title or content[:40],
            "content": content,
            "source": "财联社",
            "url": f"cls://{date}-{tm}",
            "published_at": f"{date} {tm}".strip(),
        })
    return items


def google_news(query: str, limit: int = 10, lang: str = "zh-CN") -> list[dict]:
    """Google News RSS 检索（境外源，走代理）。失败返回空列表，不阻断。"""
    url = (
        "https://news.google.com/rss/search?"
        f"q={requests.utils.quote(query)}+when:7d&hl={lang}&gl=CN&ceid=CN:zh-Hans"
    )
    try:
        with foreign_network():
            resp = requests.get(url, timeout=15)
        root = ET.fromstring(resp.content)
    except Exception as e:  # noqa: BLE001
        log.warning("Google News 失败(%s): %s", query, e)
        return []
    items = []
    for item in root.iterfind(".//item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub = (item.findtext("pubDate") or "").strip()
        try:
            pub = parsedate_to_datetime(pub).strftime("%Y-%m-%d %H:%M")
        except Exception:  # noqa: BLE001
            pub = ""
        source_el = item.find("source")
        source = source_el.text.strip() if source_el is not None and source_el.text else "GoogleNews"
        items.append({
            "ticker": None, "title": title, "content": "",
            "source": source, "url": link, "published_at": pub,
        })
        if len(items) >= limit:
            break
    return items
