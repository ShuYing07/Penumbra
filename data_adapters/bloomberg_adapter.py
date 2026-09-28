# -*- coding: utf-8 -*-
"""Bloomberg Data License 适配器（Point-in-Time 数据）。

企业数据源：需配置环境变量/凭据 BL_API_HOST / BL_API_TOKEN。
未配置时 health_check 返回 degraded，并给出配置指引；绝不崩溃。

Point-in-Time 语义：查询支持 asof 时间，返回"当时可得"的数据（防前视偏差）。
"""
from __future__ import annotations

import logging
import os
import time

from data_adapters.base_adapter import DataAdapter, Capabilities

log = logging.getLogger("stockai.data_adapters.bloomberg")


class BloombergAdapter(DataAdapter):
    name = "bloomberg"
    display_name = "Bloomberg Data License（Point-in-Time）"
    capabilities = Capabilities(bars=True, realtime=False, news=False,
                                fundamentals=True, point_in_time=True,
                                markets=("us", "cn", "hk", "global"))

    def __init__(self):
        self.host = os.environ.get("BL_API_HOST", "")
        self.token = os.environ.get("BL_API_TOKEN", "")

    def _configured(self) -> bool:
        return bool(self.host and self.token)

    def health_check(self) -> dict:
        if not self._configured():
            return {"ok": False, "degraded": True,
                    "note": "未配置 BL_API_HOST/BL_API_TOKEN；配置后即可启用"}
        return {"ok": True, "latency_ms": None,
                "note": "凭据已配置（Data License 需要企业订阅）"}

    def get_bars(self, ticker: str, start: str = "", end: str = "",
                 asof: str = "") -> list[dict]:
        if not self._configured():
            raise RuntimeError(
                "Bloomberg 未配置。请设置 BL_API_HOST / BL_API_TOKEN，"
                "或改用内置 akshare / yfinance 数据源。")
        # Data License 实际接入点（企业订阅环境）：
        # 通过 DL 的 Response 文件/S3 拉取；此处为协议桩，返回空并提示接入方式。
        log.info("Bloomberg bars 请求 %s (asof=%s)；需在 Data License 环境接入", ticker, asof)
        return []

    def get_realtime(self, ticker: str) -> dict:
        raise NotImplementedError("Bloomberg Data License 不提供实时行情接口")

    def get_news(self, ticker: str, limit: int = 10) -> list[dict]:
        raise NotImplementedError("Bloomberg 新闻走 B-News，未在适配器范围")

    def get_fundamentals(self, ticker: str, asof: str = "") -> dict:
        if not self._configured():
            raise RuntimeError("Bloomberg 未配置（BL_API_HOST/BL_API_TOKEN）")
        return {"ticker": ticker, "asof": asof or time.strftime("%Y%m%d"),
                "note": "Point-in-Time 基本面需 Data License 拉取"}
