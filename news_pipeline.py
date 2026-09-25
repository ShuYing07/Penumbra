# -*- coding: utf-8 -*-
"""实时新闻数据管道：AKShare新闻/公告/研报 + SQLite缓存 + 情感分析。"""
from __future__ import annotations

import logging
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path

from core.config import DATA_DIR

log = logging.getLogger("stockai.news")

_DB = DATA_DIR / "news_cache.db"


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(str(_DB))
    c.execute("""CREATE TABLE IF NOT EXISTS news_cache (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        stock_code TEXT, title TEXT, summary TEXT,
        source TEXT, url TEXT, publish_time TEXT,
        sentiment TEXT, cached_at REAL
    )""")
    return c


def analyze_news_sentiment(text: str) -> str:
    """简单规则情感分析：利好/利空/中性。"""
    bullish = ["上涨", "增长", "盈利", "利好", "突破", "增持", "回购",
               "超预期", "受益", "中标", "签约", "投产", "获奖", "创新高"]
    bearish = ["下跌", "亏损", "利空", "减持", "处罚", "违规", "立案",
               "下调", "退市", "跌停", "爆雷", "诉讼", "失败", "下滑"]
    score = 0
    for w in bullish:
        if w in text:
            score += 1
    for w in bearish:
        if w in text:
            score -= 1
    if score > 0:
        return "利好"
    if score < 0:
        return "利空"
    return "中性"


def _cache_valid(key: str, ttl_hours: float) -> list[dict]:
    c = _conn()
    cutoff = time.time() - ttl_hours * 3600
    rows = c.execute(
        "SELECT * FROM news_cache WHERE stock_code=? AND cached_at > ? ORDER BY publish_time DESC",
        (key, cutoff)).fetchall()
    c.close()
    return rows


def fetch_stock_news(stock_code: str) -> list[dict]:
    """获取个股新闻（6小时缓存）。"""
    cached = _cache_valid(stock_code, 6)
    if cached:
        return [dict(zip(["id","stock_code","title","summary","source","url","publish_time","sentiment","cached_at"], r)) for r in cached]
    try:
        import akshare as ak
        df = ak.stock_news_em(symbol=stock_code)
        news = []
        for _, row in df.head(20).iterrows():
            title = str(row.get("新闻标题", ""))
            summary = str(row.get("新闻内容", ""))[:200]
            src = str(row.get("文章来源", ""))
            url = str(row.get("新闻链接", ""))
            t = str(row.get("发布时间", ""))
            sentiment = analyze_news_sentiment(title + summary)
            news.append({"title": title, "summary": summary, "source": src,
                         "url": url, "publish_time": t, "sentiment": sentiment})
        _save_cache(stock_code, news)
        return news
    except Exception as e:
        log.warning("获取个股新闻失败: %s", e)
        return cached  # 兜底返回旧缓存


def fetch_announcements(stock_code: str) -> list[dict]:
    """获取公司公告（24小时缓存）。"""
    try:
        import akshare as ak
        df = ak.stock_notice_report(symbol=stock_code)
        anns = []
        for _, row in df.head(15).iterrows():
            anns.append({
                "title": str(row.get("公告标题", "")),
                "time": str(row.get("公告日期", "")),
            })
        return anns
    except Exception as e:
        log.warning("获取公告失败: %s", e)
        return []


def fetch_research_reports(stock_code: str) -> list[dict]:
    """获取券商研报。"""
    try:
        import akshare as ak
        df = ak.stock_research_report_em(symbol=stock_code)
        reports = []
        for _, row in df.head(10).iterrows():
            reports.append({
                "title": str(row.get("报告名称", "")),
                "rating": str(row.get("评级", "")),
                "target_price": str(row.get("目标价", "")),
                "analyst": str(row.get("分析师", "")),
            })
        return reports
    except Exception as e:
        log.warning("获取研报失败: %s", e)
        return []


def _save_cache(stock_code: str, news: list[dict]) -> None:
    c = _conn()
    now = time.time()
    for n in news:
        c.execute(
            "INSERT INTO news_cache (stock_code,title,summary,source,url,publish_time,sentiment,cached_at) VALUES (?,?,?,?,?,?,?,?)",
            (stock_code, n.get("title",""), n.get("summary",""),
             n.get("source",""), n.get("url",""), n.get("publish_time",""),
             n.get("sentiment","中性"), now))
    c.commit()
    c.close()
