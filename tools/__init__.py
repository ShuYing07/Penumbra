# -*- coding: utf-8 -*-
"""疏影·知微 · Agent 工具层（tools package）。

设计目标（模块一：让 AI 从"文本问答"升级为"操作专业工具的 Agent"）：

1. **统一信封**：所有工具返回同一结构
   ``{ok/success, tool, data, error, note, meta}``——LLM 与 MCP 客户端
   都按同一契约解析，不再为每种返回写一套解析逻辑。
2. **Schema 驱动**：每个工具声明一个 Pydantic 输入模型，自动生成
   JSON Schema（供 OpenAI function calling / MCP tools/list 使用），
   参数类型安全，并在调用前做校验。
3. **可治理**：每个工具带 ``risk_level``（read_only / stateful / risky），
   供上层（SAFR 治理检查点、沙箱、人工复核）做分级管控。
4. **可观测**：注册表自动记录每次调用的耗时、来源、缓存命中，写入
   ``meta``，为审计与性能分析留痕。

合规红线：工具只返回**客观数据**（行情/指标/新闻/回测统计），
绝不输出荐股建议、目标价或收益承诺。
"""
from __future__ import annotations

from tools.base import (ToolError, ToolRegistry, ToolResult, ToolSpec,
                        build_default_registry, get_registry, tool)

__all__ = [
    "ToolResult",
    "ToolSpec",
    "ToolRegistry",
    "ToolError",
    "tool",
    "get_registry",
    "build_default_registry",
]
