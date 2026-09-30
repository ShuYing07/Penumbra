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

# 视觉/多模态平台（OpenAI 兼容 image_url 消息；用于图表/截图/财报扫描件解析）
VISION_PLATFORMS = {
    "siliconflow": {
        "base_url": "https://api.siliconflow.cn/v1",
        "model": "Qwen/Qwen2.5-VL-7B-Instruct",
        "key_env": "SILICONFLOW_API_KEY",
    },
    "ollama": {
        "base_url": "http://localhost:11434/v1",
        "model": "llava:7b",  # 或 qwen2.5vl:7b / minicpm-v，装哪个用哪个
        "key_env": None,
    },
    # 金融视觉语言模型（可选，需手动拉取）：
    #   Amsi-fin-o1（基于 Qwen3-VL 4B 微调的金融 VLM，文档/图表/数值推理）
    #   COMPASS-VLM（金融文档理解 + 数值推理）
    # Ollama 拉取示例：ollama pull amsi-fin-o1  或  ollama pull qwen3-vl:7b
    "ollama_fin_vlm": {
        "base_url": "http://localhost:11434/v1",
        "model": "amsi-fin-o1",  # 若未拉取，可改为 qwen3-vl:7b / compass-vlm
        "key_env": None,
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


_VISION_CACHE: dict = {"ts": 0.0, "val": []}


def _scan_vision_platforms() -> list[str]:
    out = []
    fin_ready = False
    for name, cfg in VISION_PLATFORMS.items():
        if cfg["key_env"] is None:
            try:
                import urllib.request
                with urllib.request.urlopen(
                        "http://localhost:11434/api/tags", timeout=2) as _r:
                    _tags = _r.read().decode("utf-8", "ignore") or ""
                if cfg["model"] in _tags:
                    out.append(name)
                    if name == "ollama_fin_vlm":
                        fin_ready = True
            except Exception:  # noqa: BLE001
                pass
        elif os.environ.get(cfg["key_env"], "").strip():
            out.append(name)
    if fin_ready:
        out.sort(key=lambda n: 0 if n == "ollama_fin_vlm" else 1)
    return out


def available_vision_platforms() -> list[str]:
    """返回可用视觉平台（30s 缓存，避免高频 /api/tags 探测）。"""
    import time as _t
    if _t.time() - _VISION_CACHE["ts"] > 30 or not _VISION_CACHE["val"]:
        _VISION_CACHE["val"] = _scan_vision_platforms()
        _VISION_CACHE["ts"] = _t.time()
    return list(_VISION_CACHE["val"])


def chat_vision(prompt: str, image_path: str, platform: str = "auto",
                timeout: int = 90) -> str | None:
    """多模态调用：本地图片 + 文本 → 视觉模型输出。

    仅支持本地文件（自动 base64 内嵌）；platform=auto 时自动降级遍历。
    """
    try:
        from openai import OpenAI
    except ImportError:
        log.warning("openai未安装，无法进行多模态调用")
        return None

    import base64
    import mimetypes
    try:
        with open(image_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("ascii")
        mime = mimetypes.guess_type(image_path)[0] or "image/png"
    except OSError as e:
        log.warning("chat_vision: 图片读取失败 %s: %s", image_path, str(e)[:80])
        return None

    order = available_vision_platforms() if platform == "auto" else [platform]
    for name in order:
        cfg = VISION_PLATFORMS.get(name)
        if not cfg:
            continue
        key = os.environ.get(cfg["key_env"], "") if cfg["key_env"] else "ollama"
        try:
            client = OpenAI(api_key=key, base_url=cfg["base_url"], timeout=timeout)
            resp = client.chat.completions.create(
                model=cfg["model"],
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {
                            "url": f"data:{mime};base64,{b64}"}},
                    ],
                }],
                temperature=0.2,
                max_tokens=2048,
            )
            content = resp.choices[0].message.content or ""
            log.info("model_router: %s 视觉调用成功", name)
            return content
        except Exception as e:
            log.warning("model_router: %s 视觉失败: %s", name, str(e)[:100])
            continue
    return None


if __name__ == "__main__":
    print("可用平台:", available_platforms())
    print("可用视觉平台:", available_vision_platforms())
    r = chat("你好，一句话介绍自己", platform="auto")
    print("回复:", r[:100] if r else "无")
