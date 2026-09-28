# -*- coding: utf-8 -*-
"""LSEG（Refinitiv）Quantitative Analytics Database 适配器。

需配置 LSEG_API_KEY；未配置时 degraded 提示。接入点为企业订阅 API。
"""
from __future__ import annotations

import logging
import os

from data_adapters.base_adapter import DataAdapter, Capabilities

log = logging.getLogger("stockai.data_adapters.lseg")


class LSEGAdapter(DataAdapter):
    name = "lseg"
    display_name = "LSEG Quantitative Analytics（全球）"
    capabilities = Capabilities(bars=True, realtime=True, news=True,
                                fundamentals=True, point_in_time=False,
                                markets=("global",))

    def __init__(self):
        self.api_key = os.environ.get("LSEG_API_KEY", "")

    def _configured(self) -> bool:
        return bool(self.api_key)

    def health_check(self) -> dict:
        if not self._configured():
            return {"ok": False, "degraded": True,
                    "note": "未配置 LSEG_API_KEY；配置后即可启用"}
        return {"ok": True, "latency_ms": None, "note": "凭据已配置（企业订阅）"}

    def get_bars(self, ticker: str, start: str = "", end: str = "") -> list[dict]:
        if not self._configured():
            raise RuntimeError("LSEG 未配置（LSEG_API_KEY）")
        log.info("LSEG bars 请求 %s；需在 LSEG QAD 环境接入", ticker)
        return []

    def get_realtime(self, ticker: str) -> dict:
        raise NotImplementedError("LSEG 实时接口需 Workspace/Streaming 订阅")

    def get_news(self, ticker: str, limit: int = 10) -> list[dict]:
        raise NotImplementedError("LSEG 新闻需 NewsScope 订阅")

    def get_fundamentals(self, ticker: str) -> dict:
        if not self._configured():
            raise RuntimeError("LSEG 未配置（LSEG_API_KEY）")
        return {"ticker": ticker, "note": "QAD 基本面拉取点"}
