# -*- coding: utf-8 -*-
"""模型层级分离（provider per model tier）（2026-10 翻新 · 模块一）。

参考 TradingAgents v0.6.0「provider per model tier」：管理者与分析师不必共用
同一个模型——深度推理交给旗舰模型，机械性/高频任务交给本地或廉价模型，
成本与质量同时最优。

设计：
1. 三档算力层级：flagship（深度推理）/ balanced（常规分析）/ lite（本地或廉价，高频）；
2. 角色 → 层级映射：首席分析师、深度研究、风控、估值走旗舰；技术/新闻/情绪走
   balanced；合规校验、情感打分、摘要走 lite（优先本地 Ollama，零成本零外传）；
3. 统一入口 chat_for_role() → (content, engine, tier)，失败按层级链自动降级
   （flagship → balanced → lite → 本地），引擎名回传用于数据溯源标注；
4. 零配置：未配置任何 key 时全部落到 lite/本地，缺失即降级，绝不崩溃。

纯确定性编排，不新增依赖；LLM 调用统一走 core.model_router。
"""
from __future__ import annotations

import logging
import os
import sys
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import model_router as mr

log = logging.getLogger("stockai.model_tier")

# ---- 三档算力层级：平台优先级 ----
TIER_PLATFORMS: Dict[str, List[str]] = {
    # 旗舰：深度推理（估值/深度研究/风控/首席）
    "flagship": ["ling", "openrouter", "deepseekv4", "deepseek", "qwen35",
                 "glm", "ollama_fin", "ollama"],
    # 常规：技术/新闻/情绪/辩论
    "balanced": ["deepseek", "deepseekv4", "qwen35", "glm", "ling",
                 "ollama_fin", "ollama"],
    # 轻量：合规校验/情感/摘要——本地优先（零成本、数据不出本机）
    "lite": ["ollama_fin", "ollama", "qwen35", "glm", "deepseek"],
}

# ---- 角色 → 层级 ----
ROLE_TIERS: Dict[str, str] = {
    # 综合/管理层（深度推理）
    "manager": "flagship",
    "chief": "flagship",
    "deep_research": "flagship",
    "valuation": "flagship",
    "risk": "flagship",
    "macro": "flagship",
    "fundamental": "flagship",
    # 常规分析师
    "technical": "balanced",
    "news": "balanced",
    "sentiment": "balanced",
    "debate_bull": "balanced",
    "debate_bear": "balanced",
    "trader": "balanced",
    # 高频机械任务：本地优先
    "compliance": "lite",
    "summary": "lite",
    "classifier": "lite",
    "quality_gate": "lite",
}

# 降级链：当前层级失败后依次尝试
FALLBACK_CHAIN: Dict[str, List[str]] = {
    "flagship": ["balanced", "lite"],
    "balanced": ["lite"],
    "lite": [],
}

TIER_LABELS: Dict[str, str] = {
    "flagship": "旗舰（深度推理）",
    "balanced": "常规（性价比）",
    "lite": "轻量（本地优先）",
}


def tier_of_role(role: str) -> str:
    """角色 → 算力层级（未知角色回退 balanced）。"""
    return ROLE_TIERS.get((role or "").strip().lower(), "balanced")


def platforms_for_role(role: str) -> List[str]:
    """角色可用平台优先级（含降级链展开）。"""
    tier = tier_of_role(role)
    order = list(TIER_PLATFORMS.get(tier, TIER_PLATFORMS["balanced"]))
    for nxt in FALLBACK_CHAIN.get(tier, []):
        for p in TIER_PLATFORMS.get(nxt, []):
            if p not in order:
                order.append(p)
    return order


def available_tier_platforms(tier: str) -> List[str]:
    """过滤掉未配置 key 的平台（本地 ollama 始终可用）。"""
    avail = set(mr.available_platforms()) | {"ollama"}
    return [p for p in TIER_PLATFORMS.get(tier, []) if p in avail]


def chat_for_role(role: str, prompt: str, system: str = "",
                  timeout: int = 45,
                  max_tokens: int = 2048) -> Tuple[Optional[str], str, str]:
    """按角色层级调用模型。返回 (内容, 实际引擎名, 实际层级)。

    引擎名用于「数据来源标注」；层级用于可观测性（哪个角色用了哪档算力）。
    """
    tier = tier_of_role(role)
    tried_tiers = [tier] + list(FALLBACK_CHAIN.get(tier, []))
    for t in tried_tiers:
        for plat in TIER_PLATFORMS.get(t, []):
            cfg = mr.PLATFORMS.get(plat)
            if not cfg:
                continue
            if plat == "ollama_fin":
                resolved = mr._resolve_ollama_fin_model()
                if not resolved:
                    continue
                mr.PLATFORMS["ollama_fin"]["model"] = resolved
            try:
                content = mr.chat(prompt, system=system, platform=plat,
                                  timeout=timeout, max_tokens=max_tokens)
            except Exception as e:  # noqa: BLE001  单平台失败不影响全局
                log.debug("tier %s/%s 调用失败：%s", t, plat, e)
                continue
            if content:
                return content, plat, t
    return None, "", tier


def chat_for_task(task_type: str, prompt: str, system: str = "",
                  timeout: int = 45) -> Tuple[Optional[str], str, str]:
    """兼容旧调用：按任务类型路由（内部映射为角色→层级）。"""
    role = {"finance_report": "fundamental", "valuation": "valuation",
            "macro": "macro", "news_impact": "news",
            "tech_analysis": "technical", "sentiment": "sentiment",
            "risk": "risk", "general": "manager"}.get(task_type, "manager")
    return chat_for_role(role, prompt, system=system, timeout=timeout)


def tier_status() -> Dict[str, Dict[str, object]]:
    """各层级可用平台状态（供 UI「模型层级」面板展示）。"""
    out: Dict[str, Dict[str, object]] = {}
    for t, plats in TIER_PLATFORMS.items():
        out[t] = {"label": TIER_LABELS[t], "platforms": plats,
                  "available": available_tier_platforms(t)}
    return out


def role_table() -> List[Dict[str, str]]:
    """角色 → 层级表（UI 展示 / 审计）。"""
    return [{"role": r, "tier": t, "label": TIER_LABELS[t]}
            for r, t in sorted(ROLE_TIERS.items(), key=lambda kv: (kv[1], kv[0]))]


if __name__ == "__main__":
    assert tier_of_role("manager") == "flagship"
    assert tier_of_role("technical") == "balanced"
    assert tier_of_role("compliance") == "lite"
    assert tier_of_role("不存在角色") == "balanced"
    # 降级链：flagship → balanced → lite，且无重复
    plats = platforms_for_role("manager")
    assert plats[0] == "ling"
    assert len(plats) == len(set(plats))
    assert "ollama" in plats  # 本地兜底必须在链上
    st = tier_status()
    assert set(st) == {"flagship", "balanced", "lite"}
    assert any(r["role"] == "manager" for r in role_table())
    # 无 key 环境下调用不崩溃（返回 None，引擎空）
    txt, eng, tier = chat_for_role("compliance", "测试", timeout=3)
    assert isinstance(txt, (str, type(None))) and tier == "lite"
    print(f"model_tier self-check ok (manager→{plats[:3]}…, "
          f"compliance tier={tier}, engine={eng or 'none'})")
