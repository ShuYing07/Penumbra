# -*- coding: utf-8 -*-
"""多AI协同路由：规划(DeepSeek Pro) → 执行(免费模型并行) → 审查(GLM/Qwen)。

用法：
    python multi_ai_router.py --task "写一个RSI指标函数"
依赖：
    pip install aiohttp pyyaml
Key 从 multi_ai_config.yaml 或环境变量读取，不打印明文。
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

import aiohttp
import yaml

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "multi_ai_config.yaml"

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

# 环境变量名映射（优先从环境变量读key，yaml里写占位符也行）
ENV_MAP = {
    "deepseek_pro": "DEEPSEEK_PRO_API_KEY",
    "siliconflow": "SILICONFLOW_API_KEY",
    "groq": "GROQ_API_KEY",
    "qwen": "QWEN_API_KEY",
    "glm": "GLM_API_KEY",
}


def _load_config() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _resolve_key(provider: str, cfg: dict) -> str:
    """优先环境变量，其次yaml里的真实key；占位符 sk-xxxx 返回空。"""
    env_name = ENV_MAP.get(provider, f"{provider.upper()}_API_KEY")
    key = os.environ.get(env_name, "").strip()
    if key:
        return key
    yaml_key = (cfg.get("api_key") or "").strip()
    if yaml_key and not yaml_key.startswith("sk-xxxx") and not yaml_key.endswith("xxxx"):
        return yaml_key
    return ""


class MultiAIRouter:
    """规划→并行执行→审查 的多模型路由。任一模型失败自动降级。"""

    def __init__(self) -> None:
        self.cfg = _load_config()
        self.providers: dict[str, dict] = self.cfg.get("providers", {})
        self.routing: dict[str, Any] = self.cfg.get("routing", {})
        self._sem = asyncio.Semaphore(5)  # 并发上限

    def _provider_cfg(self, name: str) -> dict:
        p = self.providers.get(name, {})
        p["_key"] = _resolve_key(name, p)
        return p

    async def _call(self, name: str, messages: list[dict], timeout: int = 120) -> str:
        """调用单个 OpenAI 兼容端点，失败抛异常由上层 catch。"""
        p = self._provider_cfg(name)
        if not p.get("_key"):
            raise RuntimeError(f"{name}: 未配置API Key")
        url = p["base_url"].rstrip("/") + "/chat/completions"
        headers = {"Authorization": f"Bearer {p['_key']}", "Content-Type": "application/json"}
        payload = {
            "model": p["model"],
            "messages": messages,
            "temperature": 0.3,
            "max_tokens": 4096,
        }
        async with self._sem:
            async with aiohttp.ClientSession() as sess:
                async with sess.post(url, json=payload, headers=headers,
                                     timeout=aiohttp.ClientTimeout(total=timeout)) as r:
                    if r.status != 200:
                        body = await r.text()
                        raise RuntimeError(f"{name} HTTP {r.status}: {body[:200]}")
                    data = await r.json()
                    return data["choices"][0]["message"]["content"]

    async def fallback_call(self, providers: list[str], messages: list[dict]) -> tuple[str, str]:
        """按顺序尝试，成功返回 (provider_name, result)。"""
        errors = []
        for name in providers:
            try:
                result = await self._call(name, messages)
                return name, result
            except Exception as e:  # noqa: BLE001
                errors.append(f"{name}: {e}")
        raise RuntimeError("全部模型失败: " + " | ".join(errors))

    async def collaborative_analysis(self, task: str) -> dict:
        """规划→并行执行→审查。"""
        # 1. 规划
        planner = self.routing.get("planner", "deepseek_pro")
        plan_prompt = [
            {"role": "system", "content": "你是技术架构师。把任务拆解为可并行执行的子任务，每个子任务用一行描述。"},
            {"role": "user", "content": task},
        ]
        try:
            _, plan = await self._call(planner, plan_prompt, timeout=180)
        except Exception as e:  # noqa: BLE001
            fb = self.routing.get("fallback", ["qwen", "glm"])
            _, plan = await self.fallback_call(fb, plan_prompt)
            planner = f"{planner}(fallback)"

        # 2. 并行执行
        executors = self.routing.get("executor", ["siliconflow", "groq"])
        exec_prompt = [
            {"role": "system", "content": "你是资深工程师。基于规划输出代码或方案，直接给结果不要废话。"},
            {"role": "user", "content": f"任务：{task}\n规划：\n{plan}"},
        ]
        exec_tasks = [self._call(name, exec_prompt) for name in executors]
        exec_results = await asyncio.gather(*exec_tasks, return_exceptions=True)
        outputs = {}
        for name, res in zip(executors, exec_results):
            outputs[name] = res if isinstance(res, str) else f"[失败: {res}]"

        # 3. 审查
        reviewer = self.routing.get("reviewer", "glm")
        review_prompt = [
            {"role": "system", "content": "你是代码审查员。对比多个模型的输出，选最好的方案并指出问题。"},
            {"role": "user", "content": f"任务：{task}\n\n模型输出：\n" +
             "\n---\n".join(f"【{k}】\n{v}" for k, v in outputs.items())},
        ]
        try:
            _, review = await self._call(reviewer, review_prompt, timeout=120)
        except Exception:  # noqa: BLE001
            fb = self.routing.get("fallback", ["qwen"])
            _, review = await self.fallback_call(fb, review_prompt)
            reviewer = f"{reviewer}(fallback)"

        return {"planner": planner, "plan": plan, "executors": outputs,
                "reviewer": reviewer, "review": review}


async def _demo() -> None:
    router = MultiAIRouter()
    if not router.providers:
        print("⚠️  multi_ai_config.yaml 不存在或为空，跳过真实调用。")
        return
    result = await router.collaborative_analysis("写一个Python的RSI计算函数")
    print("=== 规划 ===")
    print(result["plan"][:500])
    print("\n=== 执行 ===")
    for k, v in result["executors"].items():
        print(f"[{k}] {v[:200]}")
    print("\n=== 审查 ===")
    print(result["review"][:500])


if __name__ == "__main__":
    asyncio.run(_demo())
