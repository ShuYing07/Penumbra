# -*- coding: utf-8 -*-
"""统一模型路由：所有AI平台通过OpenAI兼容格式调用，自动降级。"""
from __future__ import annotations

import os
import logging

log = logging.getLogger("stockai.model_router")

# 平台配置（OpenAI兼容端点）
PLATFORMS = {
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
        "key_env": "DEEPSEEK_API_KEY",
    },
    "qwen": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-turbo",
        "key_env": "QWEN_API_KEY",
    },
    "glm": {
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-4-flash",
        "key_env": "GLM_API_KEY",
    },
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "model": "llama-3.3-70b-versatile",
        "key_env": "GROQ_API_KEY",
    },
    "siliconflow": {
        "base_url": "https://api.siliconflow.cn/v1",
        "model": "Qwen/Qwen2.5-7B-Instruct",
        "key_env": "SILICONFLOW_API_KEY",
    },
    "ollama": {
        "base_url": "http://localhost:11434/v1",
        "model": "qwen3:7b",
        "key_env": None,  # 本地不需要key
    },
}


def available_platforms() -> list[str]:
    """返回当前配置了key的平台列表。"""
    out = []
    for name, cfg in PLATFORMS.items():
        if cfg["key_env"] is None:
            out.append(name)  # ollama本地
        elif os.environ.get(cfg["key_env"], "").strip():
            out.append(name)
    return out


def chat(prompt: str, system: str = "", platform: str = "auto",
         timeout: int = 30) -> str | None:
    """统一调用。platform=auto时自动选第一个可用的。"""
    try:
        from openai import OpenAI
    except ImportError:
        log.warning("openai未安装")
        return None

    # 确定平台顺序
    if platform == "auto":
        order = available_platforms()
    else:
        order = [platform]

    for name in order:
        cfg = PLATFORMS.get(name)
        if not cfg:
            continue
        key = os.environ.get(cfg["key_env"], "") if cfg["key_env"] else "ollama"
        try:
            client = OpenAI(
                api_key=key,
                base_url=cfg["base_url"],
                timeout=timeout,
            )
            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": prompt})
            resp = client.chat.completions.create(
                model=cfg["model"],
                messages=messages,
                temperature=0.4,
                max_tokens=1024,
            )
            content = resp.choices[0].message.content or ""
            log.info("model_router: %s 调用成功", name)
            return content
        except Exception as e:
            log.warning("model_router: %s 失败: %s", name, str(e)[:100])
            continue

    return None


if __name__ == "__main__":
    print("可用平台:", available_platforms())
    r = chat("你好，一句话介绍自己", platform="auto")
    print("回复:", r[:100] if r else "无")
