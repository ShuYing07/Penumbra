# -*- coding: utf-8 -*-
"""Wind（万得）数据源适配器（国内机构常用）。

Wind 桌面版/终端提供 Python API（WindPy）；未安装或未启动时 degraded 提示。
"""
from __future__ import annotations

import logging

from data_adapters.base_adapter import DataAdapter, Capabilities

log = logging.getLogger("stockai.data_adapters.wind")


class WindAdapter(DataAdapter):
    name = "wind"
    display_name = "Wind（万得）"
    capabilities = Capabilities(bars=True, realtime=True, news=True,
                                fundamentals=True, point_in_time=True,
                                markets=("cn", "hk"))

    def health_check(self) -> dict:
        try:
            from WindPy import w  # noqa: F401
            return {"ok": True, "latency_ms": None,
                    "note": "WindPy 已安装（需登录 Wind 终端）"}
        except ImportError:
            return {"ok": False, "degraded": True,
                    "note": "未安装 WindPy 或未登录 Wind 终端；"
                            "pip install WindPy（须有 Wind 账号）"}

    def _windpy(self):
        try:
            from WindPy import w
            return w
        except ImportError as e:
            raise RuntimeError("未安装 WindPy（pip install WindPy，需 Wind 账号）") from e

    def get_bars(self, ticker: str, start: str = "", end: str = "") -> list[dict]:
        w = self._windpy()
        if w.isconnected() == 0:
            w.start()
        code = ticker.replace("SH", "").replace("HK", "")
        data = w.wsd(code, "open,high,low,close,volume",
                     start or "2020-01-01", end or "2026-12-31",
                     "PriceAdj=F").Data
        if not data or not data[0]:
            return []
        dates = w.wsd(code, "open,high,low,close,volume",
                      start or "2020-01-01", end or "2026-12-31",
                      "PriceAdj=F").Times
        out = []
        for i, d in enumerate(dates or []):
            out.append({
                "date": str(d)[:10], "open": data[0][i], "high": data[1][i],
                "low": data[2][i], "close": data[3][i], "volume": data[4][i] or 0,
            })
        return out

    def get_realtime(self, ticker: str) -> dict:
        w = self._windpy()
        if w.isconnected() == 0:
            w.start()
        code = ticker.replace("SH", "").replace("HK", "")
        data = w.wsq(code, "rt_last,rt_pct_chg")
        if not data.Data or not data.Data[0]:
            raise RuntimeError(f"Wind 实时无数据: {ticker}")
        return {"name": ticker, "price": data.Data[0],
                "chg_pct": round(float(data.Data[1] or 0), 2)}

    def get_news(self, ticker: str, limit: int = 10) -> list[dict]:
        raise NotImplementedError("Wind 新闻接口需另订阅")

    def get_fundamentals(self, ticker: str) -> dict:
        w = self._windpy()
        if w.isconnected() == 0:
            w.start()
        code = ticker.replace("SH", "").replace("HK", "")
        data = w.wss(code, "pe_ttm,pb_mrq,total_mv", "tradeDate=20260901")
        if not data.Data:
            return {}
        return {"pe_ttm": data.Data[0], "pb": data.Data[1],
                "total_mv": data.Data[2]}
