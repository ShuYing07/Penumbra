# -*- coding: utf-8 -*-
"""内置数据源适配器：A股 akshare。

把 core/data 现有能力包装成统一适配器接口，注册进 AdapterRegistry。
"""
from __future__ import annotations

import logging
import time

from data_adapters.base_adapter import DataAdapter, Capabilities

log = logging.getLogger("stockai.data_adapters.akshare")


class AkshareAdapter(DataAdapter):
    name = "akshare"
    display_name = "AKShare（A股）"
    capabilities = Capabilities(bars=True, realtime=True, news=True,
                                fundamentals=True, point_in_time=False,
                                markets=("cn",))

    def health_check(self) -> dict:
        t0 = time.time()
        try:
            from core.data.akshare_source import fetch_realtime_cn
            fetch_realtime_cn("SH600519")  # 失败会抛
            return {"ok": True, "latency_ms": round((time.time() - t0) * 1000),
                    "note": "新浪实时可达"}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "latency_ms": None,
                    "note": f"不可达: {str(e)[:100]}"}

    def get_bars(self, ticker: str, start: str = "", end: str = "") -> list[dict]:
        from core.data.akshare_source import fetch_daily_cn
        df = fetch_daily_cn(ticker)
        return df.reset_index().to_dict("records")

    def get_realtime(self, ticker: str) -> dict:
        from core.data.akshare_source import fetch_realtime_cn
        return fetch_realtime_cn(ticker)

    def get_news(self, ticker: str, limit: int = 10) -> list[dict]:
        from core.data.akshare_source import fetch_news_cn
        return fetch_news_cn(ticker, limit)

    def get_fundamentals(self, ticker: str) -> dict:
        from core.data.akshare_source import fetch_info_cn
        return fetch_info_cn(ticker)
