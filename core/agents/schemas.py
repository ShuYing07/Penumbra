# -*- coding: utf-8 -*-
"""各智能体输出契约（pydantic 校验；解析失败时用 degraded 降级而非中断流程）。

本地小模型（7B 级别）的字段遵循度弱于云端：会把置信度写成"中等"、立场写成"看涨"、
仓位写成"20%"、布尔写成"是"。因此所有枚举/数值字段在【校验前】先做语义归一化——
这也同时加固了云端模型偶发的格式漂移。
"""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, ValidationInfo, field_validator

Stance = Literal["强烈看多", "看多", "中性", "看空", "强烈看空"]
Action = Literal["强烈买入", "买入", "观望", "回避", "卖出"]

_STANCE_MAP = {
    "看涨": "看多", "看跌": "看空", "强烈看涨": "强烈看多", "强烈看跌": "强烈看空",
    "中立": "中性", "震荡": "中性", "中性偏多": "看多", "中性偏空": "看空",
    "bullish": "看多", "bearish": "看空", "long": "看多", "short": "看空",
}
_CONF_MAP = {"很高": 90, "高": 80, "较高": 70, "偏高": 65, "中高": 65,
             "中等": 50, "中": 50, "适中": 50, "一般": 45,
             "较低": 35, "偏低": 35, "中低": 35, "低": 20, "很低": 10}
_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")


def normalize_stance(v):
    if not isinstance(v, str):
        return v
    s = v.strip()
    if s in _STANCE_MAP:
        return _STANCE_MAP[s]
    if "强烈" in s and ("多" in s or "涨" in s):
        return "强烈看多"
    if "强烈" in s and ("空" in s or "跌" in s):
        return "强烈看空"
    if "多" in s or "涨" in s or "bull" in s.lower():
        return "看多"
    if "空" in s or "跌" in s or "bear" in s.lower():
        return "看空"
    return "中性"


def normalize_confidence(v):
    if isinstance(v, bool):
        return 50
    if isinstance(v, (int, float)):
        return max(1, min(99, int(v)))
    if isinstance(v, str):
        s = v.strip().lower().rstrip("%")
        m = _NUM_RE.search(s)
        if m:
            return max(1, min(99, int(float(m.group(0)))))
        for k in sorted(_CONF_MAP, key=len, reverse=True):  # 先长后短，避免"低"抢匹配"很低"
            if k in v:
                return _CONF_MAP[k]
    return 50


def normalize_action(v):
    if not isinstance(v, str):
        return "观望"
    s = v.strip()
    if s in ("强烈买入", "买入", "观望", "回避", "卖出"):
        return s
    strong = "强烈" in s or "大幅" in s or "重仓" in s
    if any(k in s for k in ("买入", "加仓", "做多", "增持", "建仓", "进场")):
        return "强烈买入" if strong else "买入"
    if any(k in s for k in ("卖出", "清仓", "减仓", "做空", "减持", "离场", "止损", "止盈")):
        return "卖出"
    if any(k in s for k in ("回避", "不介入", "规避", "不参与", "别买", "勿")):
        return "回避"
    return "观望"  # 持有/等待/中性 等


def normalize_pct(v):
    if isinstance(v, bool) or v is None:
        return 0
    if isinstance(v, (int, float)):
        return max(0, min(100, int(v)))
    if isinstance(v, str):
        m = _NUM_RE.search(v.replace(",", ""))
        if m:
            return max(0, min(100, int(float(m.group(0)))))
    return 0


def normalize_price(v):
    """价格类：数字/数字字符串→float；None/无/否/空串/非数字→None。"""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = v.strip()
        if not s or s in ("无", "没有", "否", "null", "None", "暂无", "-"):
            return None
        m = _NUM_RE.search(s.replace(",", ""))
        if m:
            return float(m.group(0))
    return None


def normalize_prices(v):
    if not isinstance(v, list):
        return []
    out = []
    for x in v:
        p = normalize_price(x)
        if p is not None and p > 0:
            out.append(p)
    return out[:3]


def normalize_bool(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v > 0
    if isinstance(v, str):
        return v.strip().lower() in ("true", "1", "yes", "是", "对", "同意", "批准", "通过",
                                     "approve", "approved", "y")
    return False


def _flatten_text(x) -> str:
    """列表元素归一化：模型常把条目写成 {"reason":..,"source":..}，抽取其中文本。"""
    if isinstance(x, dict):
        for k in ("reason", "content", "text", "view", "point", "观点", "内容", "理由",
                  "case", "argument"):
            if x.get(k):
                return str(x[k])
        vals = [str(v) for v in x.values() if isinstance(v, (str, int, float)) and str(v)]
        return " ".join(vals)
    return str(x)


def normalize_str_list(v, limit: int):
    if isinstance(v, list):
        return [t for x in v if x is not None
                if (t := _flatten_text(x).strip())][:limit]
    if isinstance(v, str) and v.strip():
        return [v.strip()][:limit]
    return []


def normalize_text(v):
    """文本字段：None/缺失→空串；数字等→字符串。"""
    if v is None:
        return ""
    return v if isinstance(v, str) else str(v)


class AnalystSignal(BaseModel):
    stance: Stance = "中性"
    confidence: int = Field(default=50, ge=1, le=99, description="置信度 1-99")
    view: str = ""
    key_points: list[str] = Field(default_factory=list, max_length=6)
    risks: list[str] = Field(default_factory=list, max_length=5)

    @field_validator("stance", mode="before")
    @classmethod
    def _v_stance(cls, v):
        return normalize_stance(v)

    @field_validator("confidence", mode="before")
    @classmethod
    def _v_conf(cls, v):
        return normalize_confidence(v)

    @field_validator("key_points", "risks", mode="before")
    @classmethod
    def _v_lists(cls, v, info: ValidationInfo):
        limit = 6 if info.field_name == "key_points" else 5
        return normalize_str_list(v, limit)

    @field_validator("view", mode="before")
    @classmethod
    def _v_text(cls, v):
        return normalize_text(v)

    @classmethod
    def degraded(cls, node: str, err: str) -> "AnalystSignal":
        return cls(
            stance="中性", confidence=20,
            view=f"{node} 数据/调用异常，本节点结论降级为中性（{err}）。",
            key_points=["该分析师节点未能完成分析"],
            risks=["信息不完整，结论权重应降低"],
        )


class Debate(BaseModel):
    bull_case: list[str] = Field(default_factory=list, max_length=5)
    bear_case: list[str] = Field(default_factory=list, max_length=5)

    @field_validator("bull_case", "bear_case", mode="before")
    @classmethod
    def _v_lists(cls, v):
        return normalize_str_list(v, 5)

    @classmethod
    def degraded(cls, node: str, err: str) -> "Debate":
        return cls(bull_case=[], bear_case=[f"{node} 异常：{err}"])


class TraderPlan(BaseModel):
    action: Action = "观望"
    confidence: int = Field(default=50, ge=1, le=99)
    horizon: str = Field(default="", description="建议持有/观察周期")
    entry: str = Field(default="", description="入场/触发条件")
    position_pct: int = Field(default=0, ge=0, le=100, description="建议仓位百分比")
    stop_loss: float | None = Field(default=None, description="止损价")
    targets: list[float] = Field(default_factory=list, max_length=3)
    reasoning: str = ""

    @field_validator("action", mode="before")
    @classmethod
    def _v_action(cls, v):
        return normalize_action(v)

    @field_validator("confidence", mode="before")
    @classmethod
    def _v_conf(cls, v):
        return normalize_confidence(v)

    @field_validator("position_pct", mode="before")
    @classmethod
    def _v_pct(cls, v):
        return normalize_pct(v)

    @field_validator("stop_loss", mode="before")
    @classmethod
    def _v_stop(cls, v):
        return normalize_price(v)

    @field_validator("targets", mode="before")
    @classmethod
    def _v_targets(cls, v):
        return normalize_prices(v)

    @field_validator("horizon", "entry", "reasoning", mode="before")
    @classmethod
    def _v_text(cls, v):
        return normalize_text(v)

    @classmethod
    def degraded(cls, node: str, err: str) -> "TraderPlan":
        return cls(action="观望", confidence=15, horizon="未知",
                   entry="数据不足，暂不给入场条件", position_pct=0,
                   stop_loss=None, targets=[],
                   reasoning=f"{node} 异常，默认观望（{err}）")


class Scenario(BaseModel):
    label: Literal["乐观", "基准", "悲观"]
    prob_pct: int = Field(ge=0, le=95)
    price_target: float | None = None
    condition: str = ""

    @field_validator("label", mode="before")
    @classmethod
    def _v_label(cls, v):
        if isinstance(v, str):
            if "乐" in v or "牛" in v or "上" in v:
                return "乐观"
            if "悲" in v or "熊" in v or "下" in v:
                return "悲观"
        return "基准"

    @field_validator("prob_pct", mode="before")
    @classmethod
    def _v_prob(cls, v):
        return min(95, normalize_pct(v))

    @field_validator("price_target", mode="before")
    @classmethod
    def _v_pt(cls, v):
        return normalize_price(v)

    @field_validator("condition", mode="before")
    @classmethod
    def _v_text(cls, v):
        return normalize_text(v)


class RiskDecision(BaseModel):
    approved: bool = False
    adjusted_action: Action = "观望"
    adjusted_position_pct: int = Field(default=0, ge=0, le=100)
    stop_loss: float | None = None
    targets: list[float] = Field(default_factory=list)
    scenarios: list[Scenario] = Field(default_factory=list, max_length=3)
    notes: list[str] = Field(default_factory=list)

    @field_validator("approved", mode="before")
    @classmethod
    def _v_app(cls, v):
        return normalize_bool(v)

    @field_validator("adjusted_action", mode="before")
    @classmethod
    def _v_action(cls, v):
        return normalize_action(v)

    @field_validator("adjusted_position_pct", mode="before")
    @classmethod
    def _v_pct(cls, v):
        return normalize_pct(v)

    @field_validator("stop_loss", mode="before")
    @classmethod
    def _v_stop(cls, v):
        return normalize_price(v)

    @field_validator("targets", mode="before")
    @classmethod
    def _v_targets(cls, v):
        return normalize_prices(v)

    @field_validator("scenarios", mode="before")
    @classmethod
    def _v_scenarios(cls, v):
        if not isinstance(v, list):
            return []
        out = []
        for raw in v[:3]:
            if isinstance(raw, dict):
                try:
                    out.append(Scenario.model_validate(raw))
                except Exception:  # noqa: BLE001
                    continue
        return out

    @field_validator("notes", mode="before")
    @classmethod
    def _v_notes(cls, v):
        return normalize_str_list(v, 5)

    @classmethod
    def degraded(cls, node: str, err: str) -> "RiskDecision":
        return cls(approved=False, adjusted_action="观望", adjusted_position_pct=0,
                   stop_loss=None, targets=[], scenarios=[],
                   notes=[f"{node} 异常，风控默认否决开仓（{err}）"])
