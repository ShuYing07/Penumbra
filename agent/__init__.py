# -*- coding: utf-8 -*-
"""AI Agent 工具调用层：工具封装 + 意图解析 + MCP Server。

将数据/指标/新闻/回测/搜索能力封装为 Agent 可调用工具，
让程序从"按钮驱动的桌面应用"升级为"意图驱动的 AI 投研平台"。
"""
from agent.agent_core import AgentCore, extract_ticker
from agent.schemas import ToolResult
from agent.tool_defs import build_registry, call_tool

__all__ = ["AgentCore", "extract_ticker", "ToolResult", "build_registry", "call_tool"]
