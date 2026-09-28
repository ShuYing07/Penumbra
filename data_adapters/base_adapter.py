# -*- coding: utf-8 -*-
"""数据源适配器基类：统一接口契约。"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Capabilities:
    """适配器能力声明：支持的接口子集。"""
    bars: bool = False        # 历史日线
    realtime: bool = False    # 实时报价
    news: bool = False        # 新闻/公告
    fundamentals: bool = False
    point_in_time: bool = False  # Point-in-Time 数据（防前视偏差）
    markets: tuple = ()       # 支持的市场：("cn","hk","us",...)


class DataAdapter:
    """数据源适配器基类。

    子类需实现：
      - name / display_name / capabilities
      - health_check() -> dict{ok, latency_ms, note}
      - get_bars(ticker, start, end) -> list[dict]
      - get_realtime(ticker) -> dict
      - get_news(ticker, limit) -> list[dict]
      - get_fundamentals(ticker) -> dict（可选）
    未实现的方法抛 NotImplementedError，由上层按能力声明路由。
    """

    name = "base"
    display_name = "Base Adapter"
    capabilities: Capabilities = Capabilities()

    def health_check(self) -> dict:
        raise NotImplementedError

    def get_bars(self, ticker: str, start: str = "", end: str = "") -> list[dict]:
        raise NotImplementedError

    def get_realtime(self, ticker: str) -> dict:
        raise NotImplementedError

    def get_news(self, ticker: str, limit: int = 10) -> list[dict]:
        raise NotImplementedError

    def get_fundamentals(self, ticker: str) -> dict:
        raise NotImplementedError

    # ---------- 公共 ----------
    def can(self, feature: str) -> bool:
        return bool(getattr(self.capabilities, feature, False))

    def describe(self) -> dict:
        return {"name": self.name, "display_name": self.display_name,
                "capabilities": self.capabilities.__dict__}
