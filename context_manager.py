# -*- coding: utf-8 -*-
"""上下文优先级管理（参考 OpenBB 8 级上下文模型）。

8 级优先级（从高到低）：
  1. 显式上下文：用户 @ 显式标记的股票/页面/工具
  2. 技能：当前激活的分析技能（见 skill_loader）
  3. MCP 工具：已连接的数据源工具
  4. 附件文件
  5. 当前仪表盘：当前页面显示的数据（页面感知）
  6. 对话历史
  7. 全局数据：用户偏好/市场全局
  8. 网络搜索

本模块提供两块能力：
- extract_explicit_refs(text)：解析 @茅台 / @600519 显式引用 → 标准代码
- build_context_block(...)：按优先级组装注入 LLM Prompt 的上下文文本
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional

# 显式引用：@ 后跟中文名 / 代码 / 拼音
_EXPLICIT_RE = re.compile(r"@([\u4e00-\u9fa5A-Za-z0-9_.]{1,24})")


def extract_explicit_refs(text: str) -> List[str]:
    """解析用户 @ 显式指定的标的，返回标准代码列表（无法解析的保留原词）。"""
    out: List[str] = []
    for raw in _EXPLICIT_RE.findall(text or ""):
        try:
            from agent.agent_core import extract_ticker
            code = extract_ticker(raw)
            out.append(code or raw)
        except Exception:  # noqa: BLE001
            out.append(raw)
    return out


def _page_label(page: Optional[str]) -> str:
    return page or "对话分析"


def build_context_block(
    text: str,
    *,
    page: Optional[str] = None,
    stock: Optional[str] = None,
    skill: Optional[str] = None,
    history: Optional[List[Dict[str, str]]] = None,
) -> str:
    """按优先级组装上下文文本（供 LLM Prompt 注入）。

    - text:    用户本轮输入
    - page:    当前页面（如 K线图/多空辩论/回测），页面感知
    - stock:   当前选中的股票代码
    - skill:   当前激活的技能 slug（可为空，由 skill_loader 自动匹配）
    - history: 近期对话记录 [{role, content}]
    """
    blocks: List[str] = []

    # 1) 显式上下文
    refs = extract_explicit_refs(text)
    if refs:
        blocks.append(f"用户显式指定标的：{', '.join(refs)}（最高优先级，分析以它们为准）")

    # 2) 技能（调用方已匹配）
    if skill:
        blocks.append(f"当前分析技能：{skill}")

    # 5) 当前仪表盘（页面感知）
    parts = []
    if page:
        parts.append(f"当前页面：{page}")
    if stock:
        parts.append(f"当前选中股票：{stock}")
    if parts:
        blocks.append("；".join(parts))

    # 6) 对话历史（最近 6 条）
    if history:
        recent = history[-6:]
        lines = "；".join(f"{h.get('role','u')}:{h.get('content','')[:60]}" for h in recent)
        blocks.append(f"最近对话：{lines}")

    # 8) 全局数据（合规基线，固定声明）
    blocks.append("合规基线：仅输出客观数据展示，不构成任何投资建议")

    if not blocks:
        return ""
    return "\n".join(f"[上下文·{i+1}] {b}" for i, b in enumerate(blocks))
