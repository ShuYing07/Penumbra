# -*- coding: utf-8 -*-
"""AGI 认证路由器（模块一 · 参考 TOPO-2026 协作智能框架）。

把「任务类型感知路由 + 可插拔推理层」做成一个纯函数层：
- 路由器根据任务类型（technical / fundamental / debate / backtest / rag /
  report / quick / multimodal）返回模型偏好（platform + model）；
- 推理层可插拔：用户可在 config.yaml `models.task_routing` 中为每个任务
  类型指定任意 platform/model；未配置时回退到模型路由层的自动降级链；
- 轻量「门控评分」：对可用的平台组合给出候选排序，供上层选用。

设计要点（TOPO-2026 借鉴）：
- 路由规则与推理实现解耦——本模块只输出「路由决策」，不持有模型实现；
- 完美任务路由 = 规则优先 + 显式回退 + 可观测（每次决策留 reason）；
- 不引入任何新依赖；无模型可用时返回确定性降级标记。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

log = logging.getLogger("stockai.core.agi_router")

# 任务类型 → 默认模型偏好（platform, model 可为空 = 交给 model_router 自动降级）
DEFAULT_ROUTES: dict[str, dict[str, str]] = {
    # 财报/估值：优先本地金融模型或强推理模型
    "fundamental": {"platform": "auto", "model": ""},
    # 技术面：轻量快模型即可
    "technical":   {"platform": "auto", "model": ""},
    # 多空辩论：需要强推理 + 双视角
    "debate":      {"platform": "auto", "model": ""},
    # 回测解读：确定性规则为主，LLM 仅定性
    "backtest":    {"platform": "auto", "model": ""},
    # RAG 检索问答：精确、可溯源
    "rag":         {"platform": "auto", "model": ""},
    # 综合报告：最强模型
    "report":      {"platform": "auto", "model": ""},
    # 快捷问答/闲聊：最快模型
    "quick":       {"platform": "auto", "model": ""},
    # 多模态：视觉平台
    "multimodal":  {"platform": "auto", "model": ""},
}

TASK_ALIASES: dict[str, str] = {
    "技术分析": "technical", "技术面": "technical", "k线": "technical",
    "基本面": "fundamental", "财报": "fundamental", "估值": "fundamental",
    "辩论": "debate", "多空": "debate",
    "回测": "backtest", "策略": "backtest",
    "检索": "rag", "溯源": "rag", "证据": "rag",
    "报告": "report", "总结": "report", "研报": "report",
    "问答": "quick", "闲聊": "quick", "对话": "quick",
    "图片": "multimodal", "图像": "multimodal", "图表识别": "multimodal",
}


def normalize_task(task: str | None) -> str:
    """把自然语言任务描述归一为任务类型 key。"""
    if not task:
        return "quick"
    t = task.strip().lower()
    if t in DEFAULT_ROUTES:
        return t
    if t in TASK_ALIASES:
        return TASK_ALIASES[t]
    # 逐词匹配
    for word, key in TASK_ALIASES.items():
        if word in t:
            return key
    return "quick"


@dataclass
class RouteDecision:
    task: str
    platform: str
    model: str
    reason: str
    source: str = "default"   # default | config | auto
    extra: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"task": self.task, "platform": self.platform,
                "model": self.model, "reason": self.reason,
                "source": self.source, "extra": self.extra}


def _config_routes(cfg: dict | None) -> dict[str, dict[str, str]]:
    """从 config.yaml 的 models.task_routing 读取用户自定义路由。"""
    routes: dict[str, dict[str, str]] = {}
    if not cfg:
        return routes
    section = (cfg.get("models") or {}).get("task_routing") or {}
    for task, spec in section.items():
        if isinstance(spec, dict):
            routes[normalize_task(task)] = {
                "platform": str(spec.get("platform") or ""),
                "model": str(spec.get("model") or ""),
            }
    return routes


def route(task: str | None = None, cfg: dict | None = None) -> RouteDecision:
    """路由决策：config 自定义 → 默认偏好 → 自动降级。"""
    key = normalize_task(task)
    conf = _config_routes(cfg).get(key)
    if conf and conf.get("platform"):
        return RouteDecision(key, conf["platform"], conf["model"],
                             f"config 自定义路由: {key}→{conf['platform']}",
                             source="config")
    pref = DEFAULT_ROUTES[key]
    return RouteDecision(key, pref["platform"], pref["model"],
                         f"默认路由: {key}→auto 自动降级", source="default")


def gate_score(candidates: list[dict[str, str]]) -> list[dict[str, object]]:
    """轻量门控评分：对候选 (platform, model) 组合排序。

    评分规则（TOPO-2026 简化）：platform 已知权重 0.6，model 非空权重 0.4，
    "auto" 视为已知但无偏好。返回降序列表（含 score 与 reason）。
    """
    scored: list[dict[str, object]] = []
    for c in candidates:
        platform = c.get("platform") or ""
        model = c.get("model") or ""
        known = 1.0 if platform and platform != "auto" else 0.5
        has_model = 1.0 if model else 0.0
        score = round(0.6 * known + 0.4 * has_model, 2)
        scored.append({"platform": platform, "model": model, "score": score,
                       "reason": f"platform={known:.1f} model={has_model:.1f}"})
    scored.sort(key=lambda x: float(x["score"]), reverse=True)
    return scored


if __name__ == "__main__":
    # 自检
    assert normalize_task("技术面分析") == "technical"
    assert normalize_task("帮我看看财报") == "fundamental"
    assert normalize_task("辩论一下") == "debate"
    assert normalize_task("随便聊聊") == "quick"
    assert normalize_task("multimodal") == "multimodal"
    d = route("财报")
    assert d.task == "fundamental" and d.source in ("default", "config")
    cfg = {"models": {"task_routing": {"fundamental": {"platform": "ollama",
                                                       "model": "qwen2.5:7b"}}}}
    d2 = route("财报", cfg)
    assert d2.platform == "ollama" and d2.source == "config"
    scored = gate_score([{"platform": "ollama", "model": "qwen2.5:7b"},
                         {"platform": "auto", "model": ""}])
    assert scored[0]["platform"] == "ollama"
    print("agi_router self-check ok")
