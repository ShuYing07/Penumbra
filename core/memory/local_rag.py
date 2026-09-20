# -*- coding: utf-8 -*-
"""本地模型RAG：新闻存入向量库→检索→注入本地模型prompt。

解决"本地模型无法联网"问题：程序抓实时新闻→存向量库→用户提问时检索相关新闻→
连同新闻一起送给本地模型。模型不需要"知道"新闻，但能"读到"新闻。
"""
from __future__ import annotations

import logging

from core.data.news_pipeline import fetch_stock_news, fetch_announcements

log = logging.getLogger("stockai.local_rag")

# 配置
RAG_ENABLED = True
NEWS_LOOKBACK_DAYS = 7
MAX_NEWS_ITEMS = 10


def build_rag_context(stock_code: str) -> str:
    """根据股票代码检索最近新闻，拼接为上下文文本。"""
    if not RAG_ENABLED:
        return ""

    try:
        news = fetch_stock_news(stock_code, limit=MAX_NEWS_ITEMS)
        anns = fetch_announcements(stock_code, limit=5)
    except Exception as e:  # noqa: BLE001
        log.warning("RAG检索失败: %s", e)
        return ""

    parts = []
    if news:
        parts.append("【最新新闻】")
        for n in news[:MAX_NEWS_ITEMS]:
            sentiment_tag = f"[{n.get('sentiment', '中性')}]"
            parts.append(f"  {sentiment_tag} {n.get('title', '')}（{n.get('publish_time', '')[:10]}）")
            if n.get("summary"):
                parts.append(f"    {n['summary'][:100]}")

    if anns:
        parts.append("\n【公司公告】")
        for a in anns[:5]:
            parts.append(f"  {a.get('title', '')}（{a.get('publish_time', '')[:10]}）")

    return "\n".join(parts) if parts else ""


def update_rag_index(stock_code: str):
    """触发新闻抓取并更新缓存（定时调用）。"""
    try:
        fetch_stock_news(stock_code, limit=20)
        fetch_announcements(stock_code, limit=10)
        log.info("RAG索引已更新: %s", stock_code)
    except Exception as e:  # noqa: BLE001
        log.warning("RAG索引更新失败(%s): %s", stock_code, e)


def inject_news_into_prompt(prompt: str, stock_code: str) -> str:
    """把新闻上下文注入到发送给本地模型的prompt中。"""
    news_context = build_rag_context(stock_code)
    if not news_context:
        return prompt
    return (
        f"以下是关于该股票的最新新闻和公告：\n{news_context}\n\n"
        f"请基于以上信息和你已知的知识，进行客观分析。\n\n"
        f"{prompt}"
    )
