# -*- coding: utf-8 -*-
"""市场数据类工具：行情 / 实时快照 / 大盘概览 / 股票检索 / 条件筛选。

全部为只读（RiskLevel.READ_ONLY）：只取客观行情，不产出任何倾向性结论。
实现复用既有 ``agent.tool_defs`` 的业务逻辑，这里只做"标准化封装"——
统一信封、统一入参校验、统一耗时与来源留痕，避免逻辑二次实现导致漂移。
"""
from __future__ import annotations

import time
from typing import Any, Dict, Optional

from tools.base import RiskLevel, ToolResult, tool
from tools.schemas import (FetchStockIn, MarketOverviewIn, RealtimeIn,
                           ScreenerIn, SearchStocksIn)


def _t0() -> float:
    return time.perf_counter()


def _ms(t0: float) -> float:
    return round((time.perf_counter() - t0) * 1000, 1)


@tool("fetch_stock_data",
      "获取一只股票的日线行情与最新技术指标快照（收盘价/均线/MACD/RSI 等客观数值）。"
      "当用户问某只股票「现在什么价」「最近走势」「技术面如何」时使用。",
      category="market", risk=RiskLevel.READ_ONLY, input_model=FetchStockIn,
      examples=["查一下茅台的行情", "600519 最近走势怎么样"])
def fetch_stock_data(code: str) -> ToolResult:
    t0 = _t0()
    from agent.tool_defs import fetch_stock_data as _impl
    res = _impl(code)
    return _enrich(res, "fetch_stock_data", t0, source="daily_cache+akshare")


@tool("get_realtime_snapshot",
      "获取股票实时快照（现价/涨跌幅/成交额/换手）。用于「现在多少」「实时行情」。",
      category="market", risk=RiskLevel.READ_ONLY, input_model=RealtimeIn,
      examples=["腾讯现在多少钱"])
def get_realtime_snapshot(code: str) -> ToolResult:
    t0 = _t0()
    from agent.tool_defs import get_realtime_snapshot as _impl
    res = _impl(code)
    return _enrich(res, "get_realtime_snapshot", t0, source="sina_realtime")


@tool("get_market_overview",
      "今日市场概览：主要指数的点位与涨跌、北向资金等。用于「大盘怎么样」「今天市场如何」。",
      category="market", risk=RiskLevel.READ_ONLY, input_model=MarketOverviewIn,
      examples=["今天大盘怎么样"])
def get_market_overview() -> ToolResult:
    t0 = _t0()
    from agent.tool_defs import get_market_overview as _impl
    res = _impl()
    return _enrich(res, "get_market_overview", t0, source="sina+em")


@tool("search_stocks",
      "按代码/名称/拼音缩写检索股票（如 gzmt → 贵州茅台）。用于把自然语言里的"
      "公司名解析为标准代码，通常是调用其它行情工具前的第一步。",
      category="market", risk=RiskLevel.READ_ONLY, input_model=SearchStocksIn,
      examples=["茅台的代码是多少", "搜一下宁德时代"])
def search_stocks(query: str, market: Optional[str] = None, limit: int = 10) -> ToolResult:
    t0 = _t0()
    from agent.tool_defs import search_stocks as _impl
    res = _impl(query, market, limit)
    return _enrich(res, "search_stocks", t0, source="local_index")


@tool("run_screener",
      "按结构化条件（市场/板块/价格区间/涨跌幅区间）筛选股票，返回客观列表。"
      "注意：结果按条件匹配度排列，不构成推荐排序。",
      category="market", risk=RiskLevel.READ_ONLY, input_model=ScreenerIn,
      examples=["找出涨跌幅超过5%的A股"])
def run_screener(market: Optional[str] = None, board: Optional[str] = None,
                 price_min: Optional[float] = None, price_max: Optional[float] = None,
                 chg_min: Optional[float] = None, chg_max: Optional[float] = None,
                 limit: int = 20) -> ToolResult:
    t0 = _t0()
    from agent.tool_defs import _run_screener_lazy as _impl
    res = _impl(market=market, board=board, price_min=price_min,
                price_max=price_max, chg_min=chg_min, chg_max=chg_max, limit=limit)
    return _enrich(res, "run_screener", t0, source="screener")


def _enrich(res: Any, name: str, t0: float, source: str) -> ToolResult:
    """把旧式 ToolResult 补全为新信封（耗时/来源留痕），保持兼容。"""
    if isinstance(res, ToolResult):
        res.tool = res.tool or name
        res.meta.update({"latency_ms": _ms(t0), "source": source})
        return res
    if isinstance(res, dict):
        ok = bool(res.get("ok", res.get("success")))
        return ToolResult(
            ok=ok, tool=name, data=res.get("data"),
            error=str(res.get("error", "")) if not ok else "",
            note=str(res.get("note", "")),
            meta={"latency_ms": _ms(t0), "source": source},
        )
    return ToolResult.succeed(name, res, meta={"latency_ms": _ms(t0), "source": source})
