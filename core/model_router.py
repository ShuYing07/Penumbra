# -*- coding: utf-8 -*-
"""统一模型路由：所有AI平台通过OpenAI兼容格式调用，自动降级。

2026-10 升级（对齐最新开源生态调研）：
- 新增金融增强模型 Ling-3.0-flash-Fin（蚂蚁百灵，Finance Agent v2 排行榜第一，
  MIT，124B/5.1B 激活/256K 上下文；DeepInfra/OpenRouter 等提供 OpenAI 兼容端点）；
- 新增 DeepSeek-V4-Flash / Qwen3.5 系列云端端点；
- chat_for(task_type)：按任务类型路由到最优模型顺序（金融类优先 Ling）；
- local_models() / recommended_local_models() / engine_status()：本地能力探测
  与「一键复制安装命令」引导（绝不自动执行安装）。
"""
from __future__ import annotations

import os
import logging

log = logging.getLogger("stockai.model_router")

# 平台配置（OpenAI兼容端点；key 从环境变量读取，未配置自动跳过）
PLATFORMS = {
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-flash",  # 2026 现役
        "key_env": "DEEPSEEK_API_KEY",
    },
    "deepseekv4": {  # DeepSeek V4-Flash（2026-04 发布，MIT，284B/13B 激活，1M 上下文）
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-v4-flash",
        "key_env": "DEEPSEEK_API_KEY",
    },
    "ling": {  # 蚂蚁百灵金融增强模型（Finance Agent v2 榜首）
        "base_url": "https://api.deepinfra.com/v1/openai",
        "model": "inclusionAI/Ling-3.0-flash-Fin",
        "key_env": "DEEPINFRA_API_KEY",
    },
    "openrouter": {  # 聚合端点：ling / qwen3.5 / deepseek-v4 等皆可路由
        "base_url": "https://openrouter.ai/api/v1",
        "model": "inclusionai/ling-3.0-flash-fin",
        "key_env": "OPENROUTER_API_KEY",
    },
    "qwen": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-turbo",
        "key_env": "QWEN_API_KEY",
    },
    "qwen35": {  # 阿里通义 Qwen3.5 系列（2026，Apache-2.0，CJK 优秀）
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen3.5-72b-instruct",
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
        "model": "qwen3:7b",  # 装哪个用哪个，见 local_models()
        "key_env": None,  # 本地不需要key
    },
    "ollama_fin": {  # 本地金融引擎：优先 Ling GGUF，缺失则用本地最强模型
        "base_url": "http://localhost:11434/v1",
        "model": None,  # 运行时由 _resolve_ollama_fin_model() 探测
        "key_env": None,
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
        "model": "qwen3-vl:7b",  # 2026 视觉模型，缺失时降级 llava:7b
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


# ---- 任务类型路由（2026-10 升级）----
# 每个任务类型给出平台优先级：金融任务优先 Ling（Finance Agent v2 榜首），
# 通用任务优先 DeepSeek；平台缺失 key 时自动跳过，本地兜底。
TASK_MODELS: dict[str, list[str]] = {
    "finance_report": ["ling", "openrouter", "deepseekv4", "deepseek", "qwen35", "glm", "ollama_fin", "ollama"],
    "valuation":      ["ling", "openrouter", "deepseekv4", "deepseek", "qwen35", "ollama_fin", "ollama"],
    "macro":          ["ling", "deepseekv4", "deepseek", "qwen35", "glm", "ollama_fin", "ollama"],
    "news_impact":    ["deepseek", "deepseekv4", "qwen35", "ling", "glm", "ollama"],
    "tech_analysis":  ["deepseek", "deepseekv4", "qwen35", "glm", "ollama"],
    "sentiment":      ["qwen35", "deepseek", "deepseekv4", "glm", "ollama"],
    "risk":           ["deepseek", "deepseekv4", "qwen35", "ling", "ollama"],
    "general":        ["deepseek", "deepseekv4", "qwen35", "glm", "ollama"],
}
TASK_LABELS: dict[str, str] = {
    "finance_report": "财报解析（Ling 金融增强优先）",
    "valuation": "估值分析（Ling 金融增强优先）",
    "macro": "宏观分析（Ling 金融增强优先）",
    "news_impact": "新闻事件影响评估",
    "tech_analysis": "技术面分析",
    "sentiment": "情绪/舆情分析",
    "risk": "风险评估",
    "general": "通用对话",
}


def _resolve_ollama_fin_model() -> str | None:
    """探测本地已装模型，选金融最优（Ling GGUF > qwen3:14b > qwen3:7b…）。"""
    try:
        from core import llm_local
        installed = llm_local.list_models()
    except Exception:  # noqa: BLE001
        return None
    for pref in ("ling-3.0-flash-fin", "ling3.0-flash-fin", "qwen3:14b",
                 "qwen3:7b", "qwen2.5:7b-instruct-q4_k_m", "qwen2.5:7b"):
        for m in installed:
            if pref in m.lower():
                return m
    return installed[0] if installed else None


def chat_for(task_type: str = "general", prompt: str = "",
             system: str = "", timeout: int = 45) -> tuple[str | None, str]:
    """按任务类型路由到最优模型；返回 (内容, 实际引擎名)。

    引擎名用于数据溯源标注（"来源标注"）；全部失败返回 (None, "")。
    """
    order = TASK_MODELS.get(task_type, TASK_MODELS["general"])
    for name in order:
        cfg = PLATFORMS.get(name)
        if not cfg:
            continue
        if name == "ollama_fin":
            resolved = _resolve_ollama_fin_model()
            if not resolved:
                continue
            PLATFORMS["ollama_fin"]["model"] = resolved
        content = chat(prompt, system=system, platform=name, timeout=timeout,
                       max_tokens=2048)  # 金融分析需要更长输出
        if content:
            return content, name
    return None, ""


def local_models() -> list[str]:
    """探测 Ollama 已安装模型（无 Ollama/未启动返回空列表）。"""
    try:
        from core import llm_local
        return llm_local.list_models()
    except Exception:  # noqa: BLE001
        return []


def recommended_local_models() -> list[dict]:
    """2026-10 推荐的本地模型（仅提示，绝不自动安装）。"""
    return [
        {"name": "ling-3.0-flash-fin",
         "tag": "金融专用 · Finance Agent v2 榜首 · 256K 上下文",
         "desc": "蚂蚁百灵金融增强模型（GGUF 社区版，Q4 约 78GB，建议 24GB+ 显存），"
                 "财报/估值/多文档金融分析最佳",
         "pull": "ollama pull ling-3.0-flash-fin"},
        {"name": "qwen3:14b",
         "tag": "本地综合最佳（Q4 约 9GB，12-16GB 显存）",
         "desc": "2026 单卡黄金档：数学/代码/中文推理，性价比最高",
         "pull": "ollama pull qwen3:14b"},
        {"name": "qwen3-vl:7b",
         "tag": "视觉（图表/截图/扫描件）",
         "desc": "识别 K 线图、财报截图、票据（异形框），配合多模态解析使用",
         "pull": "ollama pull qwen3-vl:7b"},
        {"name": "amsi-fin-o1",
         "tag": "金融视觉语言模型（可选）",
         "desc": "基于 Qwen3-VL 微调的金融 VLM，文档+图表+数值推理",
         "pull": "ollama pull amsi-fin-o1"},
    ]


def engine_status() -> dict:
    """AI 引擎总览：云端可用平台 + 本地已装模型 + 推荐未装。"""
    cloud = []
    for name, cfg in PLATFORMS.items():
        if cfg["key_env"] is not None and os.environ.get(cfg["key_env"], "").strip():
            cloud.append(name)
    installed = local_models()
    rec = recommended_local_models()
    missing = [m["name"] for m in rec
               if not any(m["name"].lower() in x.lower() for x in installed)]
    return {
        "cloud_ready": cloud,
        "local_installed": installed,
        "recommended_missing": missing,
        "ollama_running": bool(installed),
    }


def chat(prompt: str, system: str = "", platform: str = "auto",
         timeout: int = 30, max_tokens: int = 1024) -> str | None:
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
                max_tokens=max_tokens,
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
                # 视觉模型探测：qwen3-vl > llava > amsi-fin-o1（有即用）
                if name == "ollama":
                    for pref in ("qwen3-vl", "qwen2.5vl", "llava", "minicpm-v"):
                        if pref in _tags:
                            cfg["model"] = pref
                            out.append(name)
                            break
                elif cfg["model"] in _tags:
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
