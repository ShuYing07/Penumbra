# -*- coding: utf-8 -*-
"""全球（美股/港股/日股等）与加密货币数据源：yfinance。

TUN 模式下直连可用；未开 TUN 时由 foreign_network() 注入 Clash 代理。
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import pandas as pd

from core.config import foreign_network

log = logging.getLogger("stockai.data.yf")

_COLS = ["open", "high", "low", "close", "volume", "amount"]


def fetch_daily_global(ticker: str, period: str = "2y") -> pd.DataFrame:
    import yfinance as yf

    with foreign_network():
        raw = yf.Ticker(ticker).history(period=period, interval="1d", auto_adjust=True)
    if raw is None or len(raw) == 0:
        raise RuntimeError(f"yfinance 无数据: {ticker}")
    df = raw.rename(columns=str.lower)
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    df.index = pd.to_datetime(df.index).normalize()
    df = df[~df.index.duplicated(keep="last")].sort_index()
    for c in _COLS:
        if c not in df.columns:
            df[c] = None
    log.info("全球日线 %s 行数=%d", ticker, len(df))
    return df[_COLS]


def fetch_realtime_global(ticker: str) -> dict:
    import yfinance as yf

    with foreign_network():
        t = yf.Ticker(ticker)
        price = float(t.fast_info.last_price)
        prev = float(t.fast_info.previous_close)
        name = ""
        try:
            name = t.info.get("longName") or t.info.get("shortName") or ""
        except Exception:  # noqa: BLE001
            pass
    return {
        "name": name,
        "price": round(price, 4),
        "prev_close": round(prev, 4),
        "chg_pct": round((price / prev - 1) * 100, 2) if prev else None,
    }


def fetch_info_global(ticker: str) -> dict:
    import yfinance as yf

    try:
        with foreign_network():
            info = yf.Ticker(ticker).info or {}
        keys = {
            "name": "longName", "industry": "sector", "pe_ttm": "trailingPE",
            "pb": "priceToBook", "total_market_cap": "marketCap",
            "dividend_yield": "dividendYield", "profit_margin": "profitMargins",
        }
        out = {k: info.get(v) for k, v in keys.items() if info.get(v) is not None}
        if out.get("total_market_cap"):
            out["total_market_cap"] = float(out["total_market_cap"])
        return out
    except Exception as e:  # noqa: BLE001
        log.warning("info 失败 %s: %s", ticker, e)
        return {}


def fetch_news_global(ticker: str, limit: int = 10) -> list[dict]:
    """兼容 yfinance 新旧两种 news 结构。"""
    import yfinance as yf

    try:
        with foreign_network():
            raw = yf.Ticker(ticker).news or []
    except Exception as e:  # noqa: BLE001
        log.warning("yfinance 新闻失败 %s: %s", ticker, e)
        return []

    items: list[dict] = []
    for n in raw[:limit]:
        try:
            if isinstance(n, dict) and isinstance(n.get("content"), dict):
                c = n["content"]
                ts = c.get("pubDate") or ""
                items.append({
                    "ticker": ticker,
                    "title": c.get("title", ""),
                    "content": (c.get("preview", {}) or {}).get("body", "") if isinstance(c.get("preview"), dict) else "",
                    "source": (c.get("provider", {}) or {}).get("displayName", "Yahoo"),
                    "url": (c.get("canonicalUrl", {}) or {}).get("url", ""),
                    "published_at": ts[:19].replace("T", " ") if ts else "",
                })
            else:
                ts = n.get("providerPublishTime")
                items.append({
                    "ticker": ticker,
                    "title": n.get("title", ""),
                    "content": "",
                    "source": n.get("publisher", "Yahoo"),
                    "url": n.get("link", ""),
                    "published_at": datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
                    if ts else "",
                })
        except Exception:  # noqa: BLE001
            continue
    return [it for it in items if it["title"]]
