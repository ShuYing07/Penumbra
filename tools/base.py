# -*- coding: utf-8 -*-
"""工具层基座：统一结果信封 + Schema 驱动的注册表。

为什么自己写而不用裸 dict：
- LLM 侧需要**确定的**返回结构，否则每次都要猜 data 在哪一层；
- MCP / OpenAI function calling 需要 JSON Schema，Pydantic 模型能直接生成；
- 治理层需要在调用前拿到工具的元信息（风险等级、是否只读）做分级管控。

统一信封同时提供两种写法以兼容既有代码：
- 旧：``res.ok`` / ``res.data`` / ``res.note``
- 新：``res.success`` / ``res.data`` / ``res.error`` / ``res.meta``
"""
from __future__ import annotations

import inspect
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from pydantic import BaseModel, Field

log = logging.getLogger("stockai.tools")


class RiskLevel(str, Enum):
    """工具风险等级——治理层据此决定是否需要人工复核/沙箱隔离。"""
    READ_ONLY = "read_only"      # 只读：行情、指标、新闻检索
    STATEFUL = "stateful"        # 会改变本地状态：图表操作、自选股
    COMPUTE = "compute"          # 计算密集：回测、优化（限流）
    SENSITIVE = "sensitive"      # 敏感：写库、下单模拟、导出


class ToolError(Exception):
    """工具执行失败（可被注册表捕获并转为 error 信封，而非抛出到调用方）。"""
    def __init__(self, message: str, *, hint: str = ""):
        super().__init__(message)
        self.hint = hint


# ---------------------------------------------------------------------------
# 统一结果信封
# ---------------------------------------------------------------------------
class ToolResult(BaseModel):
    """所有工具的统一返回结构。

    ``meta`` 固定包含：tool / latency_ms / ts / risk，调用方还可补充
    source（数据来源）、cached（是否命中缓存）等，供审计与溯源使用。
    """
    ok: bool = Field(description="调用是否成功")
    tool: str = Field(default="", description="工具名")
    data: Any = Field(default=None, description="结构化结果（JSON 兼容）")
    error: str = Field(default="", description="失败原因（成功时为空）")
    note: str = Field(default="", description="数据来源/口径说明（面向人读）")
    meta: Dict[str, Any] = Field(default_factory=dict, description="调用元信息：耗时/来源/风险等级")

    # ---- 兼容属性：新信封写法 ----
    @property
    def success(self) -> bool:
        """``ok`` 的别名，对齐 {success, data, error, meta} 契约。"""
        return self.ok

    def to_envelope(self) -> Dict[str, Any]:
        """按 {success, data, error, meta} 输出（MCP / 外部 Agent 生态契约）。"""
        return {
            "success": self.ok,
            "data": self.data,
            "error": self.error,
            "meta": {**self.meta, "tool": self.tool, "note": self.note},
        }

    def to_text(self, max_chars: int = 1200) -> str:
        """给 LLM 看的紧凑文本（过长自动截断，避免烧 context）。"""
        import json
        try:
            s = json.dumps(self.data, ensure_ascii=False, default=str)
        except Exception:  # noqa: BLE001
            s = str(self.data)
        if len(s) > max_chars:
            s = s[:max_chars] + f"…(已截断，共{len(s)}字符)"
        head = f"[{self.tool}] {'OK' if self.ok else 'FAIL'}"
        if self.error:
            head += f" {self.error}"
        if self.note:
            head += f" · {self.note}"
        return f"{head}\n{s}" if self.ok else f"{head}"

    # ---- 构造器 ----
    @classmethod
    def succeed(cls, tool: str, data: Any, note: str = "", **meta) -> "ToolResult":
        return cls(ok=True, tool=tool, data=data, note=note, meta=dict(meta))

    @classmethod
    def failed(cls, tool: str, error: str, note: str = "", **meta) -> "ToolResult":
        return cls(ok=False, tool=tool, data=None, error=error, note=note,
                   meta=dict(meta))


# 兼容旧代码里的 helper 命名
def ok_result(tool: str, data: Any, note: str = "", **meta) -> ToolResult:
    return ToolResult.succeed(tool, data, note=note, **meta)


def fail_result(tool: str, error: str, note: str = "", **meta) -> ToolResult:
    """兼容旧行为：失败信息同时写进 note（旧代码只读 note 展示错误）。"""
    return ToolResult.failed(tool, error, note=note or f"调用失败：{error}", **meta)


# ---------------------------------------------------------------------------
# 工具规格与注册表
# ---------------------------------------------------------------------------
@dataclass
class ToolSpec:
    """一个工具的完整元信息（供 LLM 选工具、治理层分级、MCP 暴露）。"""
    name: str
    description: str
    func: Callable[..., Any]
    input_model: Optional[type] = None     # Pydantic 输入模型
    category: str = "general"              # market / analysis / chart / research
    risk: RiskLevel = RiskLevel.READ_ONLY
    examples: List[str] = field(default_factory=list)
    timeout_s: float = 30.0

    @property
    def parameters_schema(self) -> Dict[str, Any]:
        """生成 JSON Schema（OpenAI function calling / MCP 通用）。"""
        if self.input_model is None:
            return {"type": "object", "properties": {}, "required": []}
        schema = self.input_model.model_json_schema()
        # 去掉 pydantic 自动加的 title，减少 token 消耗
        schema.pop("title", None)
        for v in schema.get("properties", {}).values():
            v.pop("title", None)
        return schema

    def to_mcp_tool(self) -> Dict[str, Any]:
        """MCP tools/list 条目。"""
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.parameters_schema,
        }

    def to_openai_tool(self) -> Dict[str, Any]:
        """OpenAI / 兼容端点的 function 定义。"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters_schema,
            },
        }


class ToolRegistry:
    """工具注册表：注册 / 列举 / 导出 Schema / 安全调用（含治理钩子）。

    调用链：``pre_hook``（SAFR 治理检查点）→ 参数校验 → 执行 → 计时 → 信封化。
    任何异常都被转成 ``ok=False`` 的信封，**绝不把栈抛给 LLM**——
    栈信息对模型是无噪声负担，对使用者是可读错误才是价值。
    """

    def __init__(self, name: str = "shuying"):
        self.name = name
        self._specs: Dict[str, ToolSpec] = {}
        self._pre_hooks: List[Callable[[str, Dict[str, Any]], Optional[str]]] = []
        self._post_hooks: List[Callable[[ToolResult], None]] = []
        self._call_count: Dict[str, int] = {}

    # ---------- 注册 ----------
    def register(self, spec: ToolSpec) -> ToolSpec:
        if spec.name in self._specs:
            log.debug("工具重复注册，覆盖：%s", spec.name)
        self._specs[spec.name] = spec
        return spec

    def add_pre_hook(self, hook) -> None:
        """前置钩子：返回非空字符串即拒绝调用（拒绝原因）。"""
        self._pre_hooks.append(hook)

    def add_post_hook(self, hook) -> None:
        """后置钩子：审计留痕 / 指标上报。"""
        self._post_hooks.append(hook)

    # ---------- 查询 ----------
    def names(self) -> List[str]:
        return sorted(self._specs)

    def get(self, name: str) -> Optional[ToolSpec]:
        return self._specs.get(name)

    def specs(self) -> List[ToolSpec]:
        return [self._specs[n] for n in self.names()]

    def mcp_tools(self) -> List[Dict[str, Any]]:
        return [s.to_mcp_tool() for s in self.specs()]

    def openai_tools(self) -> List[Dict[str, Any]]:
        return [s.to_openai_tool() for s in self.specs()]

    def describe(self) -> str:
        """给 LLM 的工具清单（按分类聚合，紧凑）。"""
        lines = []
        for spec in self.specs():
            lines.append(f"- {spec.name}（{spec.category}/{spec.risk.value}）：{spec.description}")
        return "\n".join(lines)

    def stats(self) -> Dict[str, int]:
        return dict(self._call_count)

    # ---------- 调用 ----------
    def call(self, name: str, kwargs: Optional[Dict[str, Any]] = None) -> ToolResult:
        """执行一次工具调用，永远返回 ToolResult（不抛异常）。"""
        kwargs = dict(kwargs or {})
        t0 = time.perf_counter()
        spec = self._specs.get(name)
        if spec is None:
            return ToolResult.failed(
                name, f"未知工具：{name}",
                note=f"可用工具：{', '.join(self.names())}")

        # 1) 治理前置钩子（SAFR 检查点：身份/授权/暴露限额/频次）
        for hook in self._pre_hooks:
            try:
                verdict = hook(name, kwargs)
            except Exception as e:  # noqa: BLE001  钩子自身异常不得阻断调用链
                log.warning("pre_hook 异常（忽略）：%s", e)
                continue
            if isinstance(verdict, str) and verdict:
                return ToolResult.failed(
                    name, verdict, note="被治理检查点拦截",
                    latency_ms=round((time.perf_counter() - t0) * 1000, 1),
                    risk=spec.risk.value)

        # 2) 参数校验（Pydantic）
        try:
            args = self._validate(spec, kwargs)
        except Exception as e:  # noqa: BLE001
            return ToolResult.failed(
                name, f"参数校验失败：{e}", note="请检查参数类型与取值范围",
                latency_ms=round((time.perf_counter() - t0) * 1000, 1),
                risk=spec.risk.value)

        # 3) 执行
        try:
            raw = spec.func(**args)
        except ToolError as e:
            # 工具主动抛出的已知错误：带 hint，帮助 LLM 自我纠正
            res = ToolResult.failed(name, str(e), note=e.hint)
        except Exception as e:  # noqa: BLE001
            log.exception("工具 %s 执行异常", name)
            res = ToolResult.failed(name, f"{type(e).__name__}: {e}")
        else:
            # 正常返回：归一化为信封（兼容 dict / 旧 ToolResult / 裸值）
            res = self._as_result(name, raw, spec)

        # 4) 补全元信息
        res.meta.setdefault("latency_ms", round((time.perf_counter() - t0) * 1000, 1))
        res.meta.setdefault("risk", spec.risk.value)
        res.meta.setdefault("category", spec.category)
        res.meta["tool"] = name
        self._call_count[name] = self._call_count.get(name, 0) + 1

        for hook in self._post_hooks:
            try:
                hook(res)
            except Exception as e:  # noqa: BLE001
                log.debug("post_hook 异常（忽略）：%s", e)
        return res

    # ---------- 内部 ----------
    @staticmethod
    def _validate(spec: ToolSpec, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        if spec.input_model is None:
            return kwargs
        model = spec.input_model(**kwargs)
        if hasattr(model, "model_dump"):
            return model.model_dump()
        return model.dict()

    @staticmethod
    def _as_result(name: str, raw: Any, spec: ToolSpec) -> ToolResult:
        """把函数返回值统一成 ToolResult（兼容 dict / 旧 ToolResult / 裸值）。"""
        if isinstance(raw, ToolResult):
            raw.tool = raw.tool or name
            return raw
        if isinstance(raw, dict) and ("ok" in raw or "success" in raw):
            ok = bool(raw.get("ok", raw.get("success")))
            return ToolResult(
                ok=ok, tool=name, data=raw.get("data"),
                error=str(raw.get("error", "")) if not ok else "",
                note=str(raw.get("note", "")),
                meta=dict(raw.get("meta", {})),
            )
        return ToolResult.succeed(name, raw)


# ---------------------------------------------------------------------------
# 装饰器 + 全局单例
# ---------------------------------------------------------------------------
def tool(name: str, description: str, *, category: str = "general",
         risk: RiskLevel = RiskLevel.READ_ONLY, input_model: Optional[type] = None,
         examples: Optional[List[str]] = None, registry: Optional[ToolRegistry] = None):
    """把一个函数声明为 Agent 可调用工具。

    用法::

        @tool("fetch_stock_data", "获取行情快照", category="market",
              input_model=FetchStockIn, examples=["查一下茅台的行情"])
        def fetch_stock_data(code: str): ...
    """
    def deco(fn):
        spec = ToolSpec(
            name=name,
            description=description or (fn.__doc__ or "").strip().split("\n")[0],
            func=fn,
            input_model=input_model,
            category=category,
            risk=risk,
            examples=examples or [],
        )
        (registry or _default_registry()).register(spec)
        fn.__tool_spec__ = spec  # noqa: B010
        return fn
    return deco


_REGISTRY: Optional[ToolRegistry] = None


def _default_registry() -> ToolRegistry:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = ToolRegistry()
    return _REGISTRY


def get_registry() -> ToolRegistry:
    """获取全局注册表（首次调用时按类别装配全部工具）。"""
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = build_default_registry()
    return _REGISTRY


def build_default_registry() -> ToolRegistry:
    """装配默认工具集（延迟导入，避免启动期拉起重依赖）。"""
    from tools import analysis_tools, chart_tools, market_tools  # noqa: F401
    reg = _default_registry()
    for mod in (market_tools, analysis_tools, chart_tools):
        for _, obj in inspect.getmembers(mod, inspect.isfunction):
            spec = getattr(obj, "__tool_spec__", None)
            if spec is not None:
                reg.register(spec)
    return reg
