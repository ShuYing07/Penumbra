# -*- coding: utf-8 -*-
"""AI 分析报告的结构化输出契约（Pydantic）。

与 core/agents/schemas.py（多智能体交易决策模型）互补：本模块定义面向
"分析报告展示层"的三个模型。所有模型都强制带 disclaimer 固定字段，
从结构上保证任何输出都不会脱离合规边界。
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

DISCLAIMER = "本分析仅为数据展示，不构成投资建议"


class TechnicalAnalysisReport(BaseModel):
    """技术面分析报告（程序计算指标 + 模型解读）。"""

    indicators: dict[str, Any] = Field(default_factory=dict, description="技术指标快照")
    summary: str = ""
    data_sources: list[str] = Field(default_factory=list)
    confidence: float = Field(default=50.0, ge=0, le=100)
    disclaimer: str = DISCLAIMER


class FundamentalAnalysisReport(BaseModel):
    """基本面分析报告。"""

    valuation_metrics: dict[str, Any] = Field(default_factory=dict)
    financial_health: dict[str, Any] = Field(default_factory=dict)
    risks: list[str] = Field(default_factory=list)
    disclaimer: str = DISCLAIMER


class DebateReport(BaseModel):
    """多空辩论综合报告。"""

    bull_points: list[str] = Field(default_factory=list)
    bear_points: list[str] = Field(default_factory=list)
    verdict_summary: str = ""
    disclaimer: str = DISCLAIMER


def _coerce(v: Any) -> dict[str, Any]:
    """把任意模型返回值尽力转成 dict；失败返回空 dict。"""
    if v is None:
        return {}
    if isinstance(v, BaseModel):
        return v.model_dump()
    if isinstance(v, dict):
        return v
    try:
        import json
        return json.loads(v) if isinstance(v, str) else {}
    except Exception:  # noqa: BLE001
        return {}


def parse_structured(kind: str, raw: str, payload: Any = None) -> tuple[dict, bool]:
    """尝试按 kind 解析成对应 Pydantic 模型。

    返回 (dict, ok)：
    - ok=True  → dict 为结构化模型输出（含 disclaimer）；
    - ok=False → dict 为 {"raw_text": raw}，调用方应标记"非结构化输出"。
    """
    model_map = {
        "technical": TechnicalAnalysisReport,
        "技术面": TechnicalAnalysisReport,
        "fundamental": FundamentalAnalysisReport,
        "基本面": FundamentalAnalysisReport,
        "debate": DebateReport,
        "多空辩论": DebateReport,
    }
    model = model_map.get(kind)
    candidate = _coerce(payload)
    if model is None or not candidate:
        return {"raw_text": raw, "disclaimer": DISCLAIMER}, False
    try:
        obj = model.model_validate(candidate)
        return obj.model_dump(), True
    except Exception:  # noqa: BLE001 - 解析失败降级，不崩溃
        return {"raw_text": raw, "disclaimer": DISCLAIMER}, False
