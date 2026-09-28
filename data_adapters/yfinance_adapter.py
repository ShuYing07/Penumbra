# -*- coding: utf-8 -*-
"""内置数据源适配器：Yahoo Finance（全球）。

把 yfinance 包装成统一适配器接口（含内置 IndexError 保护与字段归一）。
"""
from __future__ import annotations

import logging
import time

from data_adapters.base_adapter import DataAdapter, Capabilities

log = logging.getLogger("stockai.data_adapters.yfinance")


class YFinanceAdapter(DataAdapter):
    name = "yfinance"
    display_name = "Yahoo Finance（全球）"
    capabilities = Capabilities(bars=True, realtime=True, news=False,
                                fundamentals=True, point_in_time=False,
                                markets=("us", "hk", "cn"))

    def health_check(self) -> dict:
        t0 = time.time()
        try:
            import yfinance as yf
            t = yf.Ticker("AAPL")
            _ = t.history(period="5d", interval="1d", auto_adjust=False)
            return {"ok": True, "latency_ms": round((time.time() - t0) * 1000),
                    "note": "AAPL 历史数据可达"}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "latency_ms": None,
                    "note": f"不可达: {str(e)[:100]}"}

    def get_bars(self, ticker: str, start: str = "", end: str = "") -> list[dict]:
        import yfinance as yf
        df = yf.download(ticker, start=start or None, end=end or None,
                         auto_adjust=False, progress=False)
        if df is None or df.empty:
            return []
        df = df.reset_index()
        # 多级列（MultiIndex）扁平化
        if hasattr(df.columns, "levels"):
            df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
        col = {c.lower(): c for c in df.columns}
        date_col = col.get("date", df.columns[0])
        recs = []
        for _, r in df.iterrows():
            recs.append({
                "date": str(r[date_col])[:10],
                "open": float(r.get(col.get("open", "Open"), 0) or 0),
                "high": float(r.get(col.get("high", "High"), 0) or 0),
                "low": float(r.get(col.get("low", "Low"), 0) or 0),
                "close": float(r.get(col.get("close", "Close"), 0) or 0),
                "volume": float(r.get(col.get("volume", "Volume"), 0) or 0),
            })
        return recs

    def get_realtime(self, ticker: str) -> dict:
        import yfinance as yf
        t = yf.Ticker(ticker)
        hist = t.history(period="2d", auto_adjust=False)
        if hist is None or hist.empty:
            raise RuntimeError(f"yfinance 无数据: {ticker}")
        last = hist.iloc[-1]
        prev = hist.iloc[-2] if len(hist) > 1 else last
        price = float(last["Close"])
        prev_close = float(prev["Close"])
        return {"name": ticker, "price": price, "prev_close": prev_close,
                "chg_pct": round((price / prev_close - 1) * 100, 2) if prev_close else 0}

    def get_news(self, ticker: str, limit: int = 10) -> list[dict]:
        raise NotImplementedError("yfinance 适配器未提供新闻接口")

    def get_fundamentals(self, ticker: str) -> dict:
        import yfinance as yf
        t = yf.Ticker(ticker)
        info = t.info or {}
        return {"name": info.get("longName") or ticker,
                "pe_ttm": info.get("trailingPE"),
                "pb": info.get("priceToBook"),
                "market_cap": info.get("marketCap")}
