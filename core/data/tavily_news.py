# -*- coding: utf-8 -*-
"""Tavily AI 新闻搜索（海外服务，走系统代理），作为新闻舆情的增强源。

- key 从 .env 的 TAVILY_API_KEY 读；
- 与国内源不同，Tavily 在海外，需走 Clash 代理（trust_env=True 默认）；
- 返回 [{title, url, time}]，失败抛异常由 service 降级。
"""
from __future__ import annotations

import logging
import os

import requests

log = logging.getLogger("stockai.data.tavily")

_ENDPOINT = "https://api.tavily.com/search"


def search(query: str, max_results: int = 8) -> list[dict]:
    key = os.environ.get("TAVILY_API_KEY", "").strip()
    if not key:
        raise RuntimeError("未配置 TAVILY_API_KEY")
    resp = requests.post(
        _ENDPOINT,
        json={"api_key": key, "query": query, "max_results": max_results,
              "search_depth": "basic", "topic": "news"},
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()
    out = []
    for r in data.get("results", []):
        out.append({
            "title": (r.get("title") or "").strip(),
            "url": r.get("url", ""),
            "time": r.get("published_date") or r.get("date") or "",
            "source": "tavily",
        })
    log.info("Tavily '%s' 返回 %d 条", query, len(out))
    return out
