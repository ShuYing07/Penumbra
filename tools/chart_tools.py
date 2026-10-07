# -*- coding: utf-8 -*-
"""图表 AI 控制面工具（Agent 像用户一样操作图表）。

参考 @pairlens/fast-financial-charts 的"AI 控制面"思路：把图表操作也做成
Agent 可调用的工具，让 AI 不只是"读数据"，而是能**摆好一张图给用户看**
——加指标、画趋势线、切周期、读视窗数据、导出快照。

风险等级：STATEFUL（会改变当前会话的图表展示状态），因此治理层可对其
做频控与复核；但它不触碰任何账户/资金/文件，仍是低危操作。

合规：图表操作只涉及展示，绝不产出买卖点建议或目标价。
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from tools.base import RiskLevel, ToolResult, tool
from tools.schemas import (ChartControlIn, ChartReadIn, ChartScreenshotIn,
                           DrawingsIn)


def _t0() -> float:
    return time.perf_counter()


def _ms(t0: float) -> float:
    return round((time.perf_counter() - t0) * 1000, 1)


@tool("chart_control",
      "图表控制面：添加/移除技术指标、添加绘图（趋势线/斐波那契等）、切换周期、"
      "切换标的、重置。当用户说「加一条 60 日均线」「画个趋势线」「切到周线」时使用。",
      category="chart", risk=RiskLevel.STATEFUL, input_model=ChartControlIn,
      examples=["给茅台的图加一条 MA60", "画一条从低点到高点的斐波那契"])
def chart_control(ticker: str = "", action: str = "", id: Optional[str] = None,
                  tool: Optional[str] = None, tf: Optional[str] = None,
                  params: Optional[Dict[str, Any]] = None,
                  points: Optional[List[Dict[str, Any]]] = None,
                  meta: Optional[Dict[str, Any]] = None) -> ToolResult:
    t0 = _t0()
    from agent.tool_defs import chart_control_tool as _impl
    res = _impl(ticker=ticker, action=action, id=id, tool=tool, tf=tf,
                params=params, points=points, meta=meta)
    if isinstance(res, ToolResult):
        res.tool = "chart_control"
        res.meta.update({"latency_ms": _ms(t0), "source": "chart_engine"})
        return res
    return ToolResult.succeed("chart_control", res,
                              meta={"latency_ms": _ms(t0), "source": "chart_engine"})


@tool("get_drawings",
      "读取用户在某只股票图上画过的标注（趋势线/水平线/斐波那契/矩形），"
      "用于「我之前画了什么」「图上标注了哪些位置」。",
      category="chart", risk=RiskLevel.READ_ONLY, input_model=DrawingsIn,
      examples=["我之前在茅台图上画了什么"])
def get_drawings(code: str) -> ToolResult:
    t0 = _t0()
    from agent.tool_defs import get_drawings as _impl
    res = _impl(code)
    if isinstance(res, ToolResult):
        res.tool = "get_drawings"
        res.meta.update({"latency_ms": _ms(t0), "source": "drawings_store"})
        return res
    return ToolResult.succeed("get_drawings", res,
                              meta={"latency_ms": _ms(t0), "source": "drawings_store"})


@tool("read_visible_data",
      "读取当前图表视窗内可见的 K 线数据（最近 N 根的 OHLCV），供 Agent 结合"
      "图形做定量描述。用于「图上最近这段区间涨跌多少」。",
      category="chart", risk=RiskLevel.READ_ONLY, input_model=ChartReadIn,
      examples=["图上最近 60 根 K 线的数据"])
def read_visible_data(ticker: str = "", limit: int = 120) -> ToolResult:
    t0 = _t0()
    if not ticker:
        return ToolResult.failed("read_visible_data", "缺少标的代码",
                                 note="请先调用 chart_control 设置 ticker，或显式传入",
                                 latency_ms=_ms(t0), source="chart_engine")
    try:
        from core.data import service
        from core.data.service import normalize_ticker
        code = normalize_ticker(ticker)
        df, src = service.get_daily(code)
    except Exception as e:  # noqa: BLE001
        return ToolResult.failed("read_visible_data", f"{type(e).__name__}: {e}",
                                 latency_ms=_ms(t0), source="chart_engine")
    if df is None or df.empty:
        return ToolResult.failed("read_visible_data", "无行情数据",
                                 latency_ms=_ms(t0), source=str(src))
    tail = df.tail(int(limit))
    rows = []
    for ts, r in tail.iterrows():
        rows.append({
            "date": str(ts)[:10],
            "open": float(r.get("open", 0) or 0),
            "high": float(r.get("high", 0) or 0),
            "low": float(r.get("low", 0) or 0),
            "close": float(r.get("close", 0) or 0),
            "volume": float(r.get("volume", 0) or 0),
        })
    return ToolResult.succeed(
        "read_visible_data",
        {"ticker": code, "bars": len(rows), "rows": rows},
        note=f"最近 {len(rows)} 根 K 线（数据源：{src}）",
        latency_ms=_ms(t0), source=str(src))


@tool("chart_screenshot",
      "导出当前图表状态快照（结构化：标的/周期/已加指标/已有绘图），"
      "让 Agent 知道「用户现在看的是什么样的图」，便于给出贴合上下文的说明。",
      category="chart", risk=RiskLevel.READ_ONLY, input_model=ChartScreenshotIn,
      examples=["当前图是什么状态"])
def chart_screenshot(ticker: str = "") -> ToolResult:
    t0 = _t0()
    try:
        from core.chart_engine import ChartState
    except Exception as e:  # noqa: BLE001
        return ToolResult.failed("chart_screenshot", f"图表引擎不可用：{e}",
                                 latency_ms=_ms(t0))
    key = ticker or "_current"
    st = _states().get(key)
    if st is None:
        st = ChartState(ticker=ticker or "")
    snap = st.snapshot()
    snap["indicator_count"] = len(snap.get("indicators", []))
    snap["drawing_count"] = len(snap.get("drawings", []))
    return ToolResult.succeed("chart_screenshot", snap,
                              note="图表状态快照（结构化，非位图）",
                              latency_ms=_ms(t0), source="chart_engine")


def _states() -> Dict[str, Any]:
    """复用 chart_control_tool 内部维护的图表状态字典。

    「控制」和「读快照」必须看到同一份状态，否则 Agent 会以为自己加了指标
    但快照里没有——这类"两张皮"是控制面最容易踩的坑。
    """
    from agent.tool_defs import _chart_states as _d
    return _d
