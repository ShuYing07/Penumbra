# -*- coding: utf-8 -*-
"""分析类工具：技术指标计算 / 历史回测 / 新闻检索。

风险等级说明：
- 指标与新闻为只读；
- 回测属于 COMPUTE（计算密集，需限流），且返回时必须带"历史不代表未来"口径说明。
"""
from __future__ import annotations

import time

from tools.base import RiskLevel, ToolResult, tool
from tools.schemas import BacktestIn, IndicatorsIn, NewsIn


def _t0() -> float:
    return time.perf_counter()


def _ms(t0: float) -> float:
    return round((time.perf_counter() - t0) * 1000, 1)


def _enrich(res, name: str, t0: float, source: str) -> ToolResult:
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


@tool("calculate_indicators",
      "计算指定技术指标的最新数值（MA/BOLL/RSI/MACD 等）。只给数值与客观状态，"
      "不做买卖判断。用于「技术面怎么样」「MACD 金叉了吗」。",
      category="analysis", risk=RiskLevel.READ_ONLY, input_model=IndicatorsIn,
      examples=["算一下茅台的 MACD 和 RSI"])
def calculate_indicators(code: str,
                         indicators: list | None = None) -> ToolResult:
    t0 = _t0()
    from agent.tool_defs import calculate_indicators as _impl
    res = _impl(code, indicators or ["rsi14", "macd", "sma20", "sma60", "boll"])
    return _enrich(res, "calculate_indicators", t0, source="local_calc")


@tool("run_backtest",
      "对单只股票运行指定策略的历史回测，返回收益/回撤/胜率等统计。"
      "仅描述历史表现，不代表未来，不构成投资建议。",
      category="analysis", risk=RiskLevel.COMPUTE, input_model=BacktestIn,
      examples=["用双均线策略回测茅台", "RSI 回归策略表现如何"])
def run_backtest(code: str, strategy: str = "ma_cross",
                 params: dict | None = None) -> ToolResult:
    t0 = _t0()
    from agent.tool_defs import run_backtest_tool as _impl
    res = _impl(code, strategy, params or {})
    out = _enrich(res, "run_backtest", t0, source="local_backtest")
    # 合规口径：回测结果必须自带免责说明（防止下游 LLM 断章取义）
    if out.ok and "历史回测不代表未来" not in (out.note or ""):
        out.note = (out.note + " · 历史回测不代表未来表现，不构成投资建议").strip(" ·")
    return out


@tool("search_news",
      "检索与某只股票相关的新闻资讯（标题/来源/时间）。用于「最近有什么消息」"
      "「为什么涨跌」。只做事实聚合，不做情绪判断。",
      category="analysis", risk=RiskLevel.READ_ONLY, input_model=NewsIn,
      examples=["茅台最近有什么新闻"])
def search_news(code: str, limit: int = 8) -> ToolResult:
    t0 = _t0()
    from agent.tool_defs import search_news as _impl
    res = _impl(code, limit)
    return _enrich(res, "search_news", t0, source="news_aggregator")
