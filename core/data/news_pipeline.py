# -*- coding: utf-8 -*-
"""实时新闻数据管道：热点新闻、个股新闻、公司公告、券商研报。

数据源：AKShare（东方财富/新浪财经），带SQLite缓存和故障切换。
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta

import akshare as ak
import pandas as pd

from core.config import domestic_network
from core.data.cache import get_conn

log = logging.getLogger("stockai.news_pipeline")

# 缓存有效期（秒）
CACHE_TTL = {
    "hot_news": 3600,        # 1小时
    "stock_news": 21600,     # 6小时
    "announcements": 86400,  # 24小时
    "research": 86400,       # 24小时
}


def _ensure_table():
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS news_cache(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              stock_code TEXT,
              category TEXT,
              title TEXT,
              summary TEXT,
              source TEXT,
              url TEXT,
              publish_time TEXT,
              sentiment TEXT,
              fetched_at TEXT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_news_stock ON news_cache(stock_code, category)")


def _get_cached(stock_code: str, category: str, ttl: int) -> list[dict] | None:
    """读缓存，过期返回None。"""
    _ensure_table()
    cutoff = (datetime.now() - timedelta(seconds=ttl)).isoformat(timespec="seconds")
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT stock_code, title, summary, source, url, publish_time, sentiment
               FROM news_cache
               WHERE stock_code=? AND category=? AND fetched_at>=?
               ORDER BY publish_time DESC LIMIT 50""",
            (stock_code, category, cutoff)).fetchall()
    if not rows:
        return None
    return [dict(zip(["stock_code", "title", "summary", "source", "url", "publish_time", "sentiment"], r))
            for r in rows]


def _save_cache(stock_code: str, category: str, items: list[dict]):
    """写入缓存。"""
    _ensure_table()
    now = datetime.now().isoformat(timespec="seconds")
    with get_conn() as conn:
        for it in items:
            conn.execute(
                """INSERT INTO news_cache
                   (stock_code, category, title, summary, source, url, publish_time, sentiment, fetched_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (stock_code, category,
                 it.get("title", ""), it.get("summary", it.get("content", "")),
                 it.get("source", ""), it.get("url", ""),
                 it.get("publish_time", it.get("published_at", "")),
                 it.get("sentiment", ""), now))


def fetch_hot_news(limit: int = 20) -> list[dict]:
    """热点财经新闻（全局，不按个股）。"""
    cached = _get_cached("HOT", "hot_news", CACHE_TTL["hot_news"])
    if cached:
        return cached

    items = []
    try:
        with domestic_network():
            df = ak.stock_news_em(symbol="")
        if df is not None and len(df) > 0:
            for _, r in df.head(limit).iterrows():
                items.append({
                    "stock_code": "HOT",
                    "title": str(r.get("新闻标题", "")).strip(),
                    "summary": str(r.get("新闻内容", "")).strip()[:200],
                    "source": str(r.get("文章来源", "东方财富")),
                    "url": str(r.get("新闻链接", "")),
                    "publish_time": str(r.get("发布时间", "")),
                    "sentiment": _simple_sentiment(str(r.get("新闻内容", ""))),
                })
    except Exception as e:  # noqa: BLE001
        log.warning("fetch_hot_news失败: %s", e)

    if items:
        _save_cache("HOT", "hot_news", items)
    return items


def fetch_stock_news(stock_code: str, limit: int = 15) -> list[dict]:
    """个股新闻。stock_code如"600519"。"""
    # 归一化代码
    code = stock_code.replace("SH", "").replace("SZ", "").replace("sh", "").replace("sz", "")
    cached = _get_cached(code, "stock_news", CACHE_TTL["stock_news"])
    if cached:
        return cached

    items = []
    try:
        with domestic_network():
            df = ak.stock_news_em(symbol=code)
        if df is not None and len(df) > 0:
            for _, r in df.head(limit).iterrows():
                content = str(r.get("新闻内容", "")).strip()
                items.append({
                    "stock_code": code,
                    "title": str(r.get("新闻标题", "")).strip(),
                    "summary": content[:200],
                    "source": str(r.get("文章来源", "东方财富")),
                    "url": str(r.get("新闻链接", "")),
                    "publish_time": str(r.get("发布时间", "")),
                    "sentiment": _simple_sentiment(content),
                })
    except Exception as e:  # noqa: BLE001
        log.warning("fetch_stock_news(%s)失败: %s", code, e)

    if items:
        _save_cache(code, "stock_news", items)
    return items


def fetch_announcements(stock_code: str, ann_type: str | None = None, limit: int = 10) -> list[dict]:
    """公司公告。ann_type: 业绩/增持/减持/回购等。"""
    code = stock_code.replace("SH", "").replace("SZ", "")
    cached = _get_cached(code, "announcements", CACHE_TTL["announcements"])
    if cached:
        if ann_type:
            cached = [x for x in cached if ann_type in x.get("title", "")]
        return cached[:limit]

    items = []
    try:
        with domestic_network():
            df = ak.stock_notice_report(symbol="全部")
        if df is not None and len(df) > 0:
            # 按股票代码过滤
            code_short = code
            df = df[df["代码"].astype(str).str.contains(code_short)]
            for _, r in df.head(limit).iterrows():
                title = str(r.get("公告标题", "")).strip()
                if ann_type and ann_type not in title:
                    continue
                items.append({
                    "stock_code": code,
                    "title": title,
                    "summary": "",
                    "source": str(r.get("公告类型", "沪深交易所")),
                    "url": str(r.get("网址", "")),
                    "publish_time": str(r.get("公告日期", "")),
                    "sentiment": _simple_sentiment(title),
                })
    except Exception as e:  # noqa: BLE001
        log.warning("fetch_announcements(%s)失败: %s", code, e)

    if items:
        _save_cache(code, "announcements", items)
    return items


def fetch_research_reports(stock_code: str, limit: int = 10) -> list[dict]:
    """券商研报：评级+目标价+分析师。"""
    code = stock_code.replace("SH", "").replace("SZ", "")
    cached = _get_cached(code, "research", CACHE_TTL["research"])
    if cached:
        return cached[:limit]

    items = []
    try:
        with domestic_network():
            df = ak.stock_research_report_em(symbol=code)
        if df is not None and len(df) > 0:
            for _, r in df.head(limit).iterrows():
                items.append({
                    "stock_code": code,
                    "title": str(r.get("报告名称", "")).strip(),
                    "summary": f"评级：{r.get('东财评级', '')} | 机构：{r.get('机构', '')}",
                    "source": str(r.get("机构", "")),
                    "url": str(r.get("报告PDF链接", "")),
                    "publish_time": str(r.get("日期", "")),
                    "sentiment": _simple_sentiment(str(r.get("报告名称", ""))),
                })
    except Exception as e:  # noqa: BLE001
        log.warning("fetch_research_reports(%s)失败: %s", code, e)

    if items:
        _save_cache(code, "research", items)
    return items


def analyze_news_sentiment(text: str) -> str:
    """简单规则情感分析：利好/利空/中性。"""
    return _simple_sentiment(text)


def _simple_sentiment(text: str) -> str:
    """基于关键词的简单情感判断。"""
    bullish = ["增长", "利好", "超预期", "盈利", "突破", "上涨", "回购", "增持", "分红", "签约", "中标"]
    bearish = ["下滑", "利空", "亏损", "违规", "处罚", "下跌", "减持", "退市", "风险", "诉讼", "违约"]
    score = 0
    for w in bullish:
        if w in text:
            score += 1
    for w in bearish:
        if w in text:
            score -= 1
    if score > 0:
        return "利好"
    elif score < 0:
        return "利空"
    return "中性"


def get_all_news(stock_code: str) -> dict:
    """一键获取某股票的全部新闻数据（新闻+公告+研报）。"""
    return {
        "stock_news": fetch_stock_news(stock_code),
        "announcements": fetch_announcements(stock_code),
        "research": fetch_research_reports(stock_code),
    }
