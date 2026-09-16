# -*- coding: utf-8 -*-
"""数据服务门面：市场识别 → 选源 → 拉取 → point-in-time 缓存 → 统一返回。

规范标的代码：
- A股：SH600519 / SZ000001
- 美股：AAPL
- 港股/日股等：0700.HK / 7203.T（yfinance 格式）
- 加密：BTC-USD / ETH-USD
"""
from __future__ import annotations

import logging
import re

import pandas as pd

from core.data import akshare_source as ak_src
from core.data import cache, news_sources, yfinance_source as yf_src
from core.config import now_cn

log = logging.getLogger("stockai.data")


def market_of(ticker: str) -> str:
    t = ticker.upper()
    if re.fullmatch(r"(SH|SZ)\d{6}", t):
        return "CN"
    if re.fullmatch(r"[A-Z0-9]{2,15}-(USD|USDT|USDC)", t):
        return "CRYPTO"
    if re.fullmatch(r"\d{4,5}\.HK", t):
        return "HK"   # 港股须在通用 "." 分支之前（0700.HK / 00700.HK）
    if re.fullmatch(r"[A-Z.]{1,10}", t) and "." not in t and re.fullmatch(r"[A-Z]{1,6}", t):
        return "US"
    if "." in t:
        return "GLOBAL"
    return "UNKNOWN"


# 沪深场内 ETF 号段：沪市 51x/56x/58x（510/512/513/515/516/518/588 等），深市 159 段
_RE_CN_ETF = re.compile(r"(?:SH(?:51|56|58)\d{4}|SZ159\d{3})")


def is_cn_etf(ticker: str) -> bool:
    """是否沪深场内 ETF（日线须走腾讯源；回测免印花税/过户费）。"""
    return bool(_RE_CN_ETF.fullmatch(ticker.upper()))


def security_type(ticker: str) -> str:
    """标的类型：仅区分 A股场内 ETF；其余一律 STOCK（美股 ETF 费率与股票同，无需区分）。"""
    if market_of(ticker) == "CN" and is_cn_etf(ticker):
        return "ETF"
    return "STOCK"


def get_daily(ticker: str, use_cache: bool = True) -> tuple[pd.DataFrame, str]:
    """返回 (日线DataFrame, 数据状态说明)。优先读缓存，缺失/陈旧则联网增量补取。"""
    ticker = ticker.upper()
    market = market_of(ticker)
    cached = cache.load_bars(ticker)
    today = now_cn().strftime("%Y-%m-%d")

    fresh = len(cached) > 0 and cached.index.max().strftime("%Y-%m-%d") >= _last_trade_day_hint(today)
    if use_cache and len(cached) >= 60 and fresh:
        return cached, "cache"

    try:
        if market == "CN":
            new_df = ak_src.fetch_daily_cn(ticker)
        elif market in ("US", "HK", "GLOBAL", "CRYPTO"):
            new_df = yf_src.fetch_daily_global(ticker)
        else:
            raise ValueError(f"无法识别标的: {ticker}")
        added = cache.upsert_bars(ticker, new_df, "network")
        log.info("行情入库 %s 新增 %d 行", ticker, added)
        return cache.load_bars(ticker), f"network(+{added})"
    except Exception as e:  # noqa: BLE001
        if len(cached) > 0:
            log.warning("联网取数失败 %s: %s；使用缓存 %d 行", ticker, e, len(cached))
            return cached, f"cache-fallback({type(e).__name__})"
        raise


def get_realtime(ticker: str) -> dict:
    market = market_of(ticker)
    try:
        if market == "CN":
            r = ak_src.fetch_realtime_cn(ticker)
        else:
            r = yf_src.fetch_realtime_global(ticker)
    except Exception as e:  # noqa: BLE001
        log.warning("实时报价失败 %s: %s", ticker, e)
        r = {}
    # 休市/盘口为空（price<=0）时，用日线最新收盘兜底，避免显示 0 / -100%
    if not r.get("price") or float(r.get("price") or 0) <= 0:
        bars = cache.load_bars(ticker)
        if len(bars) < 2:
            try:
                bars, _ = get_daily(ticker)
            except Exception:  # noqa: BLE001
                pass
        if len(bars) >= 2:
            last, prev = float(bars["close"].iloc[-1]), float(bars["close"].iloc[-2])
            r.update({
                "price": round(last, 4), "prev_close": round(prev, 4),
                "chg_pct": round((last / prev - 1) * 100, 2),
                "date": bars.index[-1].strftime("%Y-%m-%d"), "source": "daily_close",
            })
        elif len(bars) == 1:
            r.update({"price": round(float(bars["close"].iloc[-1]), 4), "chg_pct": None})
    return r


def get_fundamentals(ticker: str) -> dict:
    market = market_of(ticker)
    if market == "CN":
        if is_cn_etf(ticker):
            return {"note": "场内基金/ETF：无传统个股财报指标，应关注跟踪指数、折溢价与成交额"}
        return ak_src.fetch_info_cn(ticker)
    if market == "CRYPTO":
        return {"note": "加密资产无传统财报/估值指标"}
    return yf_src.fetch_info_global(ticker)


def get_news(ticker: str, per_symbol_limit: int = 8) -> list[dict]:
    """个股新闻（落库）+ 财联社宏观快讯（A股附带）。"""
    market = market_of(ticker)
    items: list[dict] = []
    try:
        if market == "CN":
            items = ak_src.fetch_news_cn(ticker, per_symbol_limit)
            try:
                from core.data import tavily_news
                items = items + tavily_news.search(
                    f"{ak_src.cn_code6(ticker)} A股 最新消息", 5)
            except Exception as e:  # noqa: BLE001
                log.warning("Tavily新闻失败（降级）：%s", e)
        else:
            items = yf_src.fetch_news_global(ticker, per_symbol_limit)
    except Exception as e:  # noqa: BLE001
        log.warning("个股新闻失败 %s: %s", ticker, e)
    cache.upsert_news(items)

    macro: list[dict] = []
    if market == "CN":
        macro = news_sources.cls_global(limit=10)
        cache.upsert_news(macro)
    return items + macro


def _last_trade_day_hint(today_iso: str) -> str:
    """粗略的最近交易日（仅判断缓存新鲜度；周末回退到周五，节假日允许再联网尝试）。"""
    d = pd.Timestamp(today_iso)
    if d.weekday() == 5:  # 周六
        d -= pd.Timedelta(days=1)
    elif d.weekday() == 6:  # 周日
        d -= pd.Timedelta(days=2)
    return d.strftime("%Y-%m-%d")
