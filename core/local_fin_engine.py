# -*- coding: utf-8 -*-
"""领域微调 · 本地金融推理引擎（模块三）：Ling-3.0-flash-Fin 或任意 Ollama 金融模型。

设计（对齐 Ling-3.0-flash-Fin 的"金融增强模型优先"思路，保持零硬依赖）：
- 模型名来源优先级：显式参数 → config.yaml models.finance_engine → 环境变量 FINANCE_MODEL
  → 默认 "ling-3.0-flash-fin"（用户需在 Ollama 中 pull，见 docs/FAQ）。
- 推理链路：Ollama OpenAI 兼容端点（localhost:11434/v1）→ 指定金融模型；
  模型缺失时尝试本地已有模型；全部失败 → 顶层 chat_finance 降级到
  core.model_router.chat(auto) 主模型（返回内容 + 实际引擎标注，绝不静默）。
"""
from __future__ import annotations

import logging
import os

log = logging.getLogger("stockai.fin_engine")

_DEFAULT_MODEL = "ling-3.0-flash-fin"


def _configured_model() -> str:
    """按优先级解析金融模型名。"""
    try:
        import yaml
        from pathlib import Path
        cfg = Path("config.yaml")
        if cfg.exists():
            data = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
            m = (data.get("models") or {}).get("finance_engine")
            if m and str(m).strip():
                return str(m).strip()
    except Exception as e:  # noqa: BLE001
        log.debug("fin_engine: config 读取失败 %s", str(e)[:60])
    return os.environ.get("FINANCE_MODEL", "").strip() or _DEFAULT_MODEL


class LocalFinEngine:
    def __init__(self, model_name: str | None = None):
        self.model_name = (model_name or _configured_model()).strip() or _DEFAULT_MODEL

    # ---- 可用性 ----
    def is_ollama_ready(self) -> bool:
        from core import llm_local
        try:
            return llm_local.is_running() and (llm_local.has_model(self.model_name)
                                               or llm_local.has_model("llama3")  # 兜底
                                               or bool(llm_local.list_models()))
        except Exception:  # noqa: BLE001
            return False

    def available_local_models(self) -> list[str]:
        from core import llm_local
        try:
            return llm_local.list_models() or []
        except Exception:  # noqa: BLE001
            return []

    def resolve_model(self) -> str | None:
        """返回最终可用的本地模型名；无可用返回 None。"""
        from core import llm_local
        try:
            if not llm_local.is_running():
                return None
            if llm_local.has_model(self.model_name):
                return self.model_name
            models = llm_local.list_models()
            if models:
                return models[0]
        except Exception as e:  # noqa: BLE001
            log.warning("fin_engine: 解析模型失败 %s", str(e)[:60])
        return None

    # ---- 推理 ----
    def generate(self, prompt: str, system: str = "", timeout: int = 120) -> tuple[str | None, str | None]:
        """Ollama 本地推理。返回 (内容, 实际模型名)；失败 (None, None)。"""
        model = self.resolve_model()
        if model is None:
            return None, None
        try:
            from openai import OpenAI
            client = OpenAI(api_key="ollama", base_url="http://localhost:11434/v1",
                            timeout=timeout)
            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": prompt})
            resp = client.chat.completions.create(
                model=model, messages=messages, temperature=0.3, max_tokens=2048)
            content = (resp.choices[0].message.content or "").strip()
            if content:
                return content, model
        except Exception as e:  # noqa: BLE001
            log.warning("fin_engine: 本地推理失败 %s: %s", model, str(e)[:100])
        return None, None


def chat_finance(prompt: str, system: str = "", model_name: str | None = None,
                 timeout: int = 120) -> tuple[str, str]:
    """金融专用推理入口（含降级链）。

    返回 (内容, 实际引擎名)：engine ∈ {"local-finance", "local-fallback", "cloud"}。
    任何引擎都失败时返回 ("", "unavailable")——调用方应诚实提示数据不足。
    """
    eng = LocalFinEngine(model_name)
    text, model = eng.generate(prompt, system=system, timeout=timeout)
    if text:
        return text, f"local-finance({model})"

    # 降级1：本地任意模型（无指定金融模型时）
    if eng.available_local_models():
        from core import llm_local
        # generate 已尝试本地第一个模型；这里不再重复，直接走云端降级
        pass

    # 降级2：云端多模型路由
    from core.model_router import chat
    text = chat(prompt, system=system, platform="auto", timeout=timeout)
    if text:
        return text, "cloud-fallback"
    return "", "unavailable"


if __name__ == "__main__":
    eng = LocalFinEngine()
    print("配置模型:", eng.model_name)
    print("本地模型:", eng.available_local_models())
    print("可用:", eng.is_ollama_ready())
