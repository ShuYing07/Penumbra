# -*- coding: utf-8 -*-
"""多模型路由 + 结果缓存（成本优化骨架，默认不烧贵 key）。

设计（按任务复杂度分层）：
- 便宜层：technical/fundamental/sentiment/news 等分析节点 → 通义千问（默认，不变）；
- 高级层：trader/risk/portfolio/conviction 等裁决节点 → 开关 STOCKAI_DEBATE=on 时
  先试 Cohere（OpenAI 兼容端点，command-r-08-2024），失败自动降级通义；
- 开关默认 off，Cohere/GPT 配额极紧，不主动烧。
结果缓存：同 (node, user) 在 TTL 内重复调用直接返回，不重复消耗 API。
"""
from __future__ import annotations

import hashlib
import logging
import os
import time

log = logging.getLogger("stockai.llm.routing")

# 裁决类节点：开启辩论时才用高级模型
PREMIUM_NODES = {"trader", "risk", "portfolio", "conviction", "manager"}
CACHE_TTL = float(os.environ.get("STOCKAI_CACHE_TTL", "300"))  # 秒
_CACHE: dict[str, tuple[float, object]] = {}


def debate_enabled() -> bool:
    return os.environ.get("STOCKAI_DEBATE", "off").strip().lower() in ("on", "1", "true", "yes")


def is_premium(node: str) -> bool:
    n = (node or "").lower()
    return any(n.startswith(p) or p in n for p in PREMIUM_NODES)


def cache_key(node: str, user: str) -> str:
    h = hashlib.md5(f"{node}|{user}".encode("utf-8")).hexdigest()
    return h


def cache_get(node: str, user: str):
    k = cache_key(node, user)
    hit = _CACHE.get(k)
    if hit and (time.time() - hit[0]) < CACHE_TTL:
        return hit[1]
    return None


def cache_put(node: str, user: str, result) -> None:
    _CACHE[cache_key(node, user)] = (time.time(), result)


def glm_chat(system: str, user: str) -> str | None:
    """调智谱 GLM（glm-4-flash，免费耐用）做裁决层第二模型。失败返回 None。

    国内服务 trust_env=False 绕系统代理。OpenAI 兼容端点。
    """
    key = os.environ.get("GLM_API_KEY", "").strip()
    if not key:
        return None
    try:
        import httpx
        from openai import OpenAI
        client = OpenAI(api_key=key,
                        base_url="https://open.bigmodel.cn/api/paas/v4",
                        http_client=httpx.Client(trust_env=False, timeout=60))
        resp = client.chat.completions.create(
            model="glm-4-flash",
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}],
            temperature=0.4,
            response_format={"type": "json_object"},
        )
        content = resp.choices[0].message.content or "{}"
        log.info("辩论层 智谱GLM 调用成功")
        return content
    except Exception as e:  # noqa: BLE001
        log.warning("辩论层 智谱GLM 失败（降级通义）：%s", str(e)[:160])
        return None


def premium_chat(system: str, user: str) -> str | None:
    """裁决层首选智谱GLM；GLM失败再试Cohere；都不行返回None。"""
    out = glm_chat(system, user)
    if out is not None:
        return out
    return cohere_chat(system, user)
    key = os.environ.get("COHERE_API_KEY", "").strip()
    if not key:
        return None
    try:
        from openai import OpenAI
        client = OpenAI(api_key=key,
                        base_url="https://api.cohere.ai/compatibility/v1",
                        timeout=60)
        resp = client.chat.completions.create(
            model="command-r-08-2024",
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}],
            temperature=0.4,
            response_format={"type": "json_object"},
        )
        content = resp.choices[0].message.content or "{}"
        log.info("辩论层 Cohere 调用成功")
        return content
    except Exception as e:  # noqa: BLE001
        log.warning("辩论层 Cohere 失败（降级通义）：%s", str(e)[:160])
        return None
