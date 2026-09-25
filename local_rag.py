# -*- coding: utf-8 -*-
"""本地模型RAG：新闻向量化 + 检索注入Prompt。"""
from __future__ import annotations

import logging
from pathlib import Path

from core.config import DATA_DIR

log = logging.getLogger("stockai.rag")

_INDEX_DIR = DATA_DIR / "chroma_news"


def build_rag_context(stock_code: str, max_items: int = 10) -> str:
    """根据股票代码检索最近新闻，拼接为上下文文本。"""
    try:
        from news_pipeline import fetch_stock_news
        news = fetch_stock_news(stock_code)
        if not news:
            return "（暂无最新新闻）"
        lines = []
        for n in news[:max_items]:
            sentiment = n.get("sentiment", "中性")
            lines.append(f"[{sentiment}] {n['title']}（{n.get('source','')} {n.get('publish_time','')}）")
        return "\n".join(lines)
    except Exception as e:
        log.warning("RAG检索失败: %s", e)
        return "（新闻检索不可用）"


def update_rag_index(stock_code: str) -> None:
    """更新某股票的新闻索引（预取新闻到缓存）。"""
    try:
        from news_pipeline import fetch_stock_news
        fetch_stock_news(stock_code)
        log.info("RAG索引已更新: %s", stock_code)
    except Exception as e:
        log.warning("更新RAG索引失败: %s", e)
