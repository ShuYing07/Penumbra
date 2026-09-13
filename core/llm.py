# -*- coding: utf-8 -*-
"""LLM 统一封装（OpenAI 兼容）：三后端路由 + 强 JSON 输出 + 记账 + 蒸馏语料积累。

后端（backend）：
- deepseek：云端 DeepSeek（默认，质量最高，按 token 计费）；
- local：纯本地 Ollama（完全离线、零成本，速度取决于 GPU）；
- auto：先云端，遇 402/断连/超时自动切本地，一次分析内保持切换后状态。
其他：
- chat_json 强 JSON：剥离代码块、失败重试、token 记账到 SQLite；
- mock：不调任何模型的本地桩，保证管线在无模型时也能演示；
- 真实推理成功后自动写蒸馏 SFT 语料（云端=teacher / 本地=student），失败不写。
"""
from __future__ import annotations

import json
import logging
import os
import re
import time

from core.config import (
    DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, FAST_MODEL, LLM_BACKEND, LLM_MOCK,
    LOCAL_MODEL, LOCAL_OLLAMA_URL, TEMPERATURE, estimate_cost, now_cn,
)
from core.data import cache
from core import llm_routing as routing

log = logging.getLogger("stockai.llm")

_JSON_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


class LLMError(RuntimeError):
    pass


def _extract_json(text: str) -> dict:
    text = text.strip()
    text = _JSON_FENCE.sub("", text).strip()
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        return json.loads(m.group(0))
    raise json.JSONDecodeError("no json object", text, 0)


class LLMRunner:
    def __init__(self, model: str | None = None, temperature: float = TEMPERATURE,
                 mock: bool | None = None, backend: str | None = None,
                 local_model: str | None = None):
        self.backend = (backend or LLM_BACKEND or "deepseek").strip().lower()
        self.model = model or FAST_MODEL
        self.local_model = (local_model or os.environ.get("STOCKAI_LOCAL_MODEL")
                            or LOCAL_MODEL)
        self.temperature = temperature
        self.mock = LLM_MOCK if mock is None else mock
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.cost_cny = 0.0
        self.meta: dict = {}          # 由管线注入（如 ticker），随蒸馏语料记录
        self.backend_used = None      # 本次实际使用的后端（auto 切换后变化）
        self._client_cloud = None
        self._client_local = None
        self._cloud_fatal: str | None = None
        self._switched_to_local = False
        if not self.mock:
            self._init_clients()

    # ---------- 客户端 ----------
    def _init_clients(self) -> None:
        import httpx
        from openai import OpenAI

        if self.backend in ("deepseek", "auto"):
            if DEEPSEEK_API_KEY:
                self._client_cloud = OpenAI(
                    api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL, timeout=90)
            elif self.backend == "deepseek":
                raise LLMError("未配置 DEEPSEEK_API_KEY（或用本地引擎/设置 STOCKAI_MOCK=1）")
        if self.backend in ("local", "auto"):
            from core import llm_local

            if not llm_local.is_running():
                if self.backend == "local" and not llm_local.ensure_started():
                    raise LLMError(
                        "本地模型服务(Ollama)不可用：未安装请访问 https://ollama.com/download ，"
                        "或改用 auto/云端引擎")
            if self.backend == "local" and llm_local.is_running() \
                    and not llm_local.has_model(self.local_model):
                raise LLMError(
                    f"本地缺少模型 {self.local_model}，请先在'本地模型'中下载，或改用 3B 小模型")
            # auto 模式本地不在线不报错（等云端失败时才会尝试，届时再诊断）
            if llm_local.is_running():
                # 回环地址必须绕过系统代理（Clash 等会劫持 127.0.0.1）
                self._client_local = OpenAI(
                    api_key="ollama", base_url=f"{LOCAL_OLLAMA_URL}/v1",
                    http_client=httpx.Client(trust_env=False, timeout=600))

    # ---------- 入口 ----------
    def chat_json(self, node: str, system: str, user: str, retries: int = 2,
                  raw: bool = False) -> dict | str:
        """调 LLM。raw=True 时返回原始 content 字符串（不解析、不记 SFT），
        供教师批量生成场景（curriculum 自行落 source=curriculum 语料）。"""
        if self.mock:
            return "[]" if raw else self._mock(node, user)

        # 结果缓存：同 (node, user) TTL 内直接返回，不重复烧 API
        if not raw:
            hit = routing.cache_get(node, user)
            if hit is not None:
                log.info("LLM 缓存命中 node=%s", node)
                return hit

        order: list[str] = []
        if self.backend == "local":
            order = ["local"]
        elif self.backend == "deepseek":
            order = ["deepseek"]
        else:  # auto
            order = ["deepseek", "local"] if not self._switched_to_local else ["local"]

        # 裁决节点 + 辩论开关：先试 Cohere，成功直接用，失败降级通义
        if (not raw and routing.debate_enabled() and routing.is_premium(node)
                and self.backend in ("deepseek", "auto")):
            content = routing.premium_chat(system, user)
            if content is not None:
                try:
                    parsed = _extract_json(content)
                    routing.cache_put(node, user, parsed)
                    self.backend_used = "cohere"
                    return parsed
                except Exception:  # noqa: BLE001
                    log.warning("Cohere 输出解析失败，降级通义")

        last_err: Exception | None = None
        for be in order:
            try:
                return self._call(be, node, system, user, retries, raw)
            except _SwitchToLocal as e:
                self._switched_to_local = True
                self._cloud_fatal = str(e)
                log.warning("云端不可用，auto 切换本地引擎：%s", e)
                if self._client_local is None:
                    self._init_local_lazy()
                continue
            except Exception as e:  # noqa: BLE001
                last_err = e
                if be == "local":
                    raise LLMError(f"本地模型连续失败 node={node}: {e}") from e
        raise LLMError(f"LLM 不可用（{last_err}）")

    def _init_local_lazy(self) -> None:
        import httpx
        from core import llm_local
        from openai import OpenAI

        if not llm_local.ensure_started():
            raise LLMError("云端不可用且本地 Ollama 未安装/未启动：https://ollama.com/download")
        if not llm_local.has_model(self.local_model):
            raise LLMError(f"云端不可用且本地缺少模型 {self.local_model}，请先下载")
        self._client_local = OpenAI(
            api_key="ollama", base_url=f"{LOCAL_OLLAMA_URL}/v1",
            http_client=httpx.Client(trust_env=False, timeout=600))

    # ---------- 单后端调用 ----------
    def _call(self, backend: str, node: str, system: str, user: str,
              retries: int, raw: bool = False) -> dict | str:
        if backend == "deepseek":
            client, model = self._client_cloud, self.model
            if self._cloud_fatal:
                raise _SwitchToLocal(self._cloud_fatal)
        else:
            if self._client_local is None:
                raise _SwitchToLocal("本地引擎未就绪")
            client, model = self._client_local, self.local_model

        last_err: Exception | None = None
        extra_hint = ""
        for attempt in range(retries + 1):
            try:
                resp = client.chat.completions.create(
                    model=model,
                    messages=[{"role": "system", "content": system},
                              {"role": "user", "content": user + extra_hint}],
                    temperature=self.temperature,
                    response_format={"type": "json_object"},
                )
                content = resp.choices[0].message.content or "{}"
                u = getattr(resp, "usage", None)
                pt = getattr(u, "prompt_tokens", 0) or 0
                ct = getattr(u, "completion_tokens", 0) or 0
                cost = estimate_cost(model, pt, ct) if backend == "deepseek" else 0.0
                self.prompt_tokens += pt
                self.completion_tokens += ct
                self.cost_cny += cost
                cache.record_tokens(node, model if backend == "deepseek"
                                    else f"local:{model}", pt, ct, cost)
                self.backend_used = backend
                if not raw:
                    # 蒸馏语料：真实输出才记录（失败/桩不记录）；raw 由调用方自行记
                    try:
                        from core.training import distill

                        distill.record_sft(
                            node=node, system=system, user=user, response=content,
                            model=model, source="teacher" if backend == "deepseek" else "student",
                            meta=self.meta)
                    except Exception:  # noqa: BLE001
                        pass
                    obj = _extract_json(content)
                    routing.cache_put(node, user, obj)
                    return obj
                return content  # raw：返回原始字符串，供教师批量生成
            except Exception as e:  # noqa: BLE001
                last_err = e
                msg = str(e)
                log.warning("LLM[%s] 调用失败 node=%s attempt=%d: %s",
                            backend, node, attempt + 1, msg[:200])
                # 云端：402 或 断连/超时 → auto 模式切本地；纯 deepseek 模式 402 直接抛
                if backend == "deepseek":
                    if "402" in msg or "Insufficient Balance" in msg:
                        text = "DeepSeek 余额不足(402)"
                        if self.backend == "auto":
                            raise _SwitchToLocal(text) from e
                        self._cloud_fatal = text + "，请充值或改用本地/auto 引擎"
                        raise LLMError(self._cloud_fatal) from e
                    if self.backend == "auto" and self._is_conn_error(e):
                        raise _SwitchToLocal(f"云端连接异常：{type(e).__name__}") from e
                # 本地模型连接类错误直接抛，不做无意义重试
                if backend == "local" and self._is_conn_error(e):
                    raise LLMError(f"本地模型服务异常：{type(e).__name__}: {e}") from e
                extra_hint = ("\n\n注意：你上一次的回复无法被解析为 JSON，"
                              "请【只输出】一个合法 JSON 对象，不要输出解释或代码块。")
                time.sleep(1.5 * (attempt + 1))
        raise LLMError(f"LLM 连续失败 node={node}: {last_err}")

    @staticmethod
    def _is_conn_error(e: Exception) -> bool:
        name = type(e).__name__.lower()
        msg = str(e).lower()
        return ("connection" in name or "timeout" in name or "apiconnection" in name
                or "connection" in msg or "timed out" in msg)

    def usage(self) -> dict:
        return {
            "model": self.model if self.backend_used != "local" else f"local:{self.local_model}",
            "backend": self.backend_used or self.backend,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.prompt_tokens + self.completion_tokens,
            "cost_cny": round(self.cost_cny, 4),
        }

    # ---------- 离线桩 ----------
    def _mock(self, node: str, user_facts: str) -> dict:
        """根据事实文本构造与各节点 schema 兼容的桩响应（确定性、可演示）。"""
        text = user_facts
        bullish_signals = sum(k in text for k in ("MACD金叉", "RSI",)) and "低于30" in text.replace(" ", "")
        bearish_signals = "MACD死叉" in text
        stance = "看多" if bullish_signals else ("看空" if bearish_signals else "中性")
        confidence = 55
        common = {
            "confidence": confidence,
            "view": f"[离线演示模式-{node}] 基于给定事实，当前信号偏{stance}，结论仅供管线联调。",
            "key_points": ["[MOCK] 该结论由本地桩生成，未经过大模型推理"],
            "risks": ["[MOCK] 实盘前必须切换真实 LLM"],
        }
        if node.startswith(("technical", "fundamental", "news", "sentiment")):
            return {"stance": stance, **common}
        if node.startswith("debate"):
            return {
                "bull_case": ["[MOCK] 技术形态存在修复可能", "[MOCK] 估值/情绪有支撑因素"],
                "bear_case": ["[MOCK] 趋势与量能尚不确认", "[MOCK] 外部风险仍在"],
            }
        if node == "trader":
            return {
                "action": "观望" if stance == "中性" else ("买入" if stance == "看多" else "回避"),
                "confidence": confidence, "horizon": "2-6周(演示)",
                "entry": "[MOCK] 回踩关键均线且放量确认后分批介入",
                "position_pct": 0 if stance != "看多" else 20,
                "stop_loss": None, "targets": [],
                "reasoning": "[MOCK] 等待更多确认信号，控制仓位。",
            }
        return {
            "approved": stance == "看多",
            "adjusted_action": "观望" if stance != "看多" else "买入",
            "adjusted_position_pct": 15 if stance == "看多" else 0,
            "stop_loss": None, "targets": [],
            "notes": ["[MOCK] 风控默认低仓位、严止损"],
        }


class _SwitchToLocal(Exception):
    """auto 模式内部信号：云端不可用，切到本地引擎。"""
