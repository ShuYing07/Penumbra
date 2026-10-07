# -*- coding: utf-8 -*-
"""Agent 工具调用层的 Pydantic 结构化 Schema（兼容层）。

历史背景：早期 Schema 定义在本文件。模块一重构后，工具层的**单一真源**
迁到 ``tools/``（``tools.schemas`` 输入模型 + ``tools.base.ToolResult`` 信封），
本文件保留旧名字并原样 re-export，使既有调用方（agent_core / tool_defs /
MCP / 测试）零改动继续工作。

新增能力（向下兼容，字段均为可选默认值）：
- ``ToolResult.error``：失败原因（旧代码只有 note 一个字段，语义混淆）
- ``ToolResult.meta``：耗时/来源/风险等级等元信息（审计与性能分析）
- ``ToolResult.success``：``ok`` 的别名，对齐 {success, data, error, meta} 契约
- ``ToolResult.to_envelope()`` / ``to_text()``：给 MCP 客户端与 LLM 用
"""
from __future__ import annotations

from tools.base import ToolResult, fail_result, ok_result
from tools.schemas import (BacktestIn, ChartControlIn, ChartReadIn,
                           ChartScreenshotIn, DrawingsIn, FetchStockIn,
                           IndicatorsIn, MarketOverviewIn, NewsIn, RealtimeIn,
                           ScreenerIn, SearchStocksIn)

__all__ = [
    # 输入 Schema（旧名保持不变）
    "FetchStockIn", "IndicatorsIn", "NewsIn", "BacktestIn", "SearchStocksIn",
    "MarketOverviewIn", "RealtimeIn", "DrawingsIn", "ScreenerIn", "ChartControlIn",
    # 新增（图表 AI 控制面）
    "ChartReadIn", "ChartScreenshotIn",
    # 统一输出
    "ToolResult", "ok_result", "fail_result",
]
