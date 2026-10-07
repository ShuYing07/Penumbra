# -*- coding: utf-8 -*-
"""合规数字孪生 + SAFR 运行时治理检查点。

两部分，分别对应两个前沿来源：

**① SAFR（Safeguards for Agentic Finance at Runtime，MAS 2026 白皮书）**
四组件：Agent Identity（代理身份）/ Controls Repository（控制库）/
Disposition Engine（处置引擎）/ Audit Log（防篡改审计日志）。
核心动作：Agent 提出的每个动作**在执行前**被打包成 Governance Envelope，
经检查点验证并记录，产出四种处置之一：
  - auto_execute：在授权范围内，自动执行
  - escalate：超阈值/证据不足 → 转人工复核（超时默认拒绝，不能"拖过去"）
  - deny：违反硬性控制 → 直接拒绝
  - observe：允许执行但留痕监控（低风险但需取样审计）

**② 合规数字孪生（Compliance Digital Twin）**
在真实执行前，先在孪生环境里**模拟执行一次**（不产生任何副作用），
用校准过的规则/模型评估其合规性，只有通过的才被允许在真实环境执行。
对金融 Agent 尤其重要：动作不可逆（转账、下单、披露），
"先模拟、后执行"把事后审计前移到事前拦截。

本实现保持**确定性可测**：评估逻辑全部是规则，不依赖 LLM，
因此可单测、可复现；需要 LLM 做语义判断时由调用方注入 judge 函数。
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

log = logging.getLogger("stockai.security.twin")

# 处置结果
AUTO_EXECUTE = "auto_execute"
ESCALATE = "escalate"
DENY = "deny"
OBSERVE = "observe"
DISPOSITIONS = (AUTO_EXECUTE, ESCALATE, DENY, OBSERVE)


# ---------------------------------------------------------------------------
# ① 代理身份
# ---------------------------------------------------------------------------
@dataclass
class AgentIdentity:
    """代理身份：谁（委托人）授权了哪个 Agent、它能做什么、授权到第几层。"""
    agent_id: str
    principal: str = "local-user"          # 委托人（人类主体）
    capabilities: set = field(default_factory=set)   # 允许的动作集合
    delegation_depth: int = 0              # 授权层级（0=本人直接授权）
    registered_at: float = field(default_factory=time.time)

    def may(self, action: str) -> bool:
        return (not self.capabilities) or (action in self.capabilities)


# ---------------------------------------------------------------------------
# ② 控制库
# ---------------------------------------------------------------------------
@dataclass
class Controls:
    """机构可配置的控制项（对应白皮书 Table 1）。"""
    # 暴露限额：单笔阈值 / 日累计阈值（超过转人工）
    exposure_per_action: Dict[str, float] = field(default_factory=dict)
    exposure_daily: float = float("inf")
    # 频控：窗口内最大动作数（防 Agent 失控/提示注入导致高频动作）
    rate_max_calls: int = 60
    rate_window_s: float = 60.0
    # 证据质量：最低置信度 + 是否必须附带证据
    min_confidence: float = 0.0
    require_evidence: bool = False
    # 人工复核超时（秒）：超时默认拒绝，避免"挂着就算通过"
    review_timeout_s: float = 3600.0
    # 高风险动作（永不自动执行）
    always_escalate: set = field(default_factory=set)

    @classmethod
    def conservative(cls) -> "Controls":
        """保守预设：适合默认开启（零配置即安全）。"""
        return cls(exposure_per_action={"transfer": 0.0, "trade": 0.0},
                   exposure_daily=0.0, rate_max_calls=20, rate_window_s=60.0,
                   min_confidence=0.6, require_evidence=True,
                   always_escalate={"transfer", "withdraw", "disclose"})


# ---------------------------------------------------------------------------
# ③ 治理信封
# ---------------------------------------------------------------------------
@dataclass
class GovernanceEnvelope:
    """Agent 在动作前提交的治理信封（白皮书的核心数据结构）。"""
    agent_id: str
    action: str
    params: Dict[str, Any] = field(default_factory=dict)
    value: float = 0.0                     # 金额/规模（用于暴露限额）
    confidence: float = 1.0                # Agent 自评置信度 0-1
    evidence: List[Dict[str, Any]] = field(default_factory=list)
    trace: List[str] = field(default_factory=list)   # 推理轨迹摘要
    context: Dict[str, Any] = field(default_factory=dict)
    reversible: bool = True                # 是否可逆（不可逆 → 更严格）
    regulatory_sensitive: bool = False     # 是否涉及监管敏感（披露/报送）

    def to_dict(self) -> Dict[str, Any]:
        return {"agent_id": self.agent_id, "action": self.action,
                "params": dict(self.params), "value": self.value,
                "confidence": self.confidence, "evidence": list(self.evidence),
                "trace": list(self.trace), "context": dict(self.context),
                "reversible": self.reversible,
                "regulatory_sensitive": self.regulatory_sensitive}


# ---------------------------------------------------------------------------
# ④ 防篡改审计日志（哈希链）
# ---------------------------------------------------------------------------
class TamperEvidentLog:
    """哈希链审计日志：任何一条被篡改都会导致 verify() 失败。"""

    def __init__(self):
        self._records: List[Dict[str, Any]] = []
        self._prev = "0" * 64

    @staticmethod
    def _hash(payload: str, prev: str) -> str:
        return hashlib.sha256(f"{prev}|{payload}".encode("utf-8")).hexdigest()

    def append(self, kind: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        body = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
        h = self._hash(body, self._prev)
        rec = {"ts": round(time.time(), 3), "kind": kind, "payload": payload,
               "prev_hash": self._prev, "hash": h}
        self._records.append(rec)
        self._prev = h
        return rec

    def verify(self) -> bool:
        prev = "0" * 64
        for r in self._records:
            body = json.dumps(r["payload"], ensure_ascii=False,
                              sort_keys=True, default=str)
            if r["prev_hash"] != prev or self._hash(body, prev) != r["hash"]:
                return False
            prev = r["hash"]
        return True

    def records(self) -> List[Dict[str, Any]]:
        return list(self._records)

    def __len__(self) -> int:
        return len(self._records)


# ---------------------------------------------------------------------------
# ⑤ 处置引擎
# ---------------------------------------------------------------------------
class DispositionEngine:
    """按控制库评估信封，产出四种处置之一（含理由，便于事后解释）。"""

    def __init__(self, controls: Optional[Controls] = None):
        self.controls = controls or Controls()
        self._calls: Dict[Tuple[str, str], List[float]] = {}
        self._daily_used: Dict[str, float] = {}

    # ---- 各控制项检查 ----
    def _check_identity(self, env: GovernanceEnvelope, agent: Optional[AgentIdentity]):
        if agent is None:
            return False, "代理未注册：无身份证明，一律拒绝"
        if not agent.may(env.action):
            return False, f"动作 {env.action} 超出该代理授权范围"
        return True, "身份与授权通过"

    def _check_exposure(self, env: GovernanceEnvelope) -> Tuple[bool, str, bool]:
        """返回 (是否致命, 说明, 是否需转人工)。"""
        if env.action in self.controls.always_escalate:
            return False, f"{env.action} 属于高风险动作，必须人工复核", True
        cap = self.controls.exposure_per_action.get(env.action)
        if cap is not None and env.value > cap:
            return False, f"单笔规模 {env.value} 超过限额 {cap}", True
        used = self._daily_used.get(env.agent_id, 0.0) + env.value
        if used > self.controls.exposure_daily:
            return False, f"日累计 {used} 超过日限额 {self.controls.exposure_daily}", True
        return True, "暴露限额内", False

    def _check_rate(self, env: GovernanceEnvelope) -> Tuple[bool, str]:
        key = (env.agent_id, env.action)
        now = time.time()
        window = self.controls.rate_window_s
        hist = [t for t in self._calls.get(key, []) if now - t <= window]
        hist.append(now)
        self._calls[key] = hist
        if len(hist) > self.controls.rate_max_calls:
            return False, (f"频次超限：{window}s 内 {len(hist)} 次 "
                           f"> {self.controls.rate_max_calls}")
        return True, f"频次正常（{len(hist)}/{self.controls.rate_max_calls}）"

    def _check_evidence(self, env: GovernanceEnvelope) -> Tuple[bool, str, bool]:
        if self.controls.require_evidence and not env.evidence:
            return False, "缺少证据：该动作要求必须附带可溯源证据", True
        if env.confidence < self.controls.min_confidence:
            return False, (f"置信度 {env.confidence:.2f} 低于门槛 "
                           f"{self.controls.min_confidence:.2f}"), True
        return True, "证据质量合格", False

    def evaluate(self, env: GovernanceEnvelope,
                 agent: Optional[AgentIdentity] = None) -> Dict[str, Any]:
        checks: List[Dict[str, Any]] = []
        escalate_reasons: List[str] = []

        ok, why = self._check_identity(env, agent)
        checks.append({"control": "authorization", "passed": ok, "detail": why})
        if not ok:
            return self._result(env, DENY, checks, [why])

        ok, why, esc = self._check_exposure(env)
        checks.append({"control": "exposure_limits", "passed": ok, "detail": why})
        if not ok:
            escalate_reasons.append(why)
            if not esc:
                return self._result(env, DENY, checks, escalate_reasons)

        ok, why = self._check_rate(env)
        checks.append({"control": "rate_limits", "passed": ok, "detail": why})
        if not ok:
            return self._result(env, DENY, checks, [why])

        ok, why, esc = self._check_evidence(env)
        checks.append({"control": "evidence_quality", "passed": ok, "detail": why})
        if not ok:
            escalate_reasons.append(why)
            if not esc:
                return self._result(env, DENY, checks, escalate_reasons)

        if escalate_reasons:
            return self._result(env, ESCALATE, checks, escalate_reasons)

        # 通过全部控制 → 依风险特征决定"自动执行"还是"执行并留痕观察"
        if env.regulatory_sensitive or not env.reversible:
            return self._result(env, OBSERVE, checks,
                                ["涉及不可逆/监管敏感动作：允许执行但全程留痕监控"])
        return self._result(env, AUTO_EXECUTE, checks, [])

    @staticmethod
    def _result(env, disposition, checks, reasons) -> Dict[str, Any]:
        return {"disposition": disposition, "action": env.action,
                "agent_id": env.agent_id, "checks": checks,
                "reasons": reasons, "allowed": disposition in (AUTO_EXECUTE, OBSERVE),
                "ts": round(time.time(), 3)}


# ---------------------------------------------------------------------------
# ⑥ 合规数字孪生：先模拟、后执行
# ---------------------------------------------------------------------------
class ComplianceTwin:
    """把治理检查点 + 数字孪生模拟串起来的运行时护栏。

    用法::

        twin = ComplianceTwin()
        twin.register_agent(AgentIdentity("analyst-1", capabilities={"query"}))
        res = twin.execute(envelope, executor=lambda e: {...真实副作用...})
        # res["executed"] 为 True 才说明真的执行了
    """

    def __init__(self, controls: Optional[Controls] = None,
                 judge: Optional[Callable[[GovernanceEnvelope], Tuple[bool, str]]] = None):
        self.controls = controls or Controls()
        self.engine = DispositionEngine(self.controls)
        self.audit = TamperEvidentLog()
        self._agents: Dict[str, AgentIdentity] = {}
        self._primary: Optional[str] = None   # 首个注册的代理（工具钩子的默认身份）
        self._judge = judge      # 可选：外部注入的语义评审（如 LLM 评审员）

    # ---- 身份 ----
    def register_agent(self, identity: AgentIdentity) -> AgentIdentity:
        self._agents[identity.agent_id] = identity
        if self._primary is None:
            self._primary = identity.agent_id
        self.audit.append("register", {"agent_id": identity.agent_id,
                                       "principal": identity.principal,
                                       "capabilities": sorted(identity.capabilities)})
        return identity

    def agent(self, agent_id: str) -> Optional[AgentIdentity]:
        return self._agents.get(agent_id)

    # ---- 孪生模拟 ----
    def simulate(self, env: GovernanceEnvelope) -> Dict[str, Any]:
        """在数字孪生中模拟执行：不产生任何副作用，只评估。"""
        agent = self._agents.get(env.agent_id)
        verdict = self.engine.evaluate(env, agent)
        # 外部语义评审（可选）：模拟环境的"校准评估器"
        judge_verdict = None
        if self._judge is not None:
            try:
                ok, why = self._judge(env)
                judge_verdict = {"passed": bool(ok), "detail": str(why)}
                if not ok and verdict["disposition"] == AUTO_EXECUTE:
                    verdict["disposition"] = ESCALATE
                    verdict["allowed"] = False
                    verdict["reasons"].append(f"孪生评估未通过：{why}")
            except Exception as e:  # noqa: BLE001
                log.warning("孪生评估器异常（忽略）：%s", e)
        sim = {"dry_run": True, "side_effects": [],
               "verdict": verdict, "judge": judge_verdict,
               "simulated_at": round(time.time(), 3)}
        self.audit.append("simulate", {**env.to_dict(), "verdict": verdict["disposition"]})
        return sim

    # ---- 真实执行（带闸门）----
    def execute(self, env: GovernanceEnvelope,
                executor: Callable[[GovernanceEnvelope], Any]) -> Dict[str, Any]:
        sim = self.simulate(env)
        verdict = sim["verdict"]
        out = {"simulation": sim, "executed": False, "result": None,
               "disposition": verdict["disposition"]}
        if not verdict["allowed"]:
            out["blocked_reason"] = "；".join(verdict["reasons"]) or "处置结果为不允许执行"
            self.audit.append("block", {**env.to_dict(),
                                        "disposition": verdict["disposition"],
                                        "reason": out["blocked_reason"]})
            return out
        try:
            out["result"] = executor(env)
            out["executed"] = True
        except Exception as e:  # noqa: BLE001
            out["error"] = f"{type(e).__name__}: {e}"
            self.audit.append("error", {**env.to_dict(), "error": out["error"]})
            return out
        self.audit.append("execute", {**env.to_dict(),
                                      "disposition": verdict["disposition"]})
        return out

    # ---- 接入工具层（AgentCore.add_tool_gate）----
    def gate_for_tools(self) -> Callable[[str, Dict[str, Any]], Optional[str]]:
        """生成工具调用前置钩子：非 auto_execute/observe 一律拦截。"""
        def _gate(name: str, kwargs: Dict[str, Any]) -> Optional[str]:
            env = GovernanceEnvelope(
                agent_id=kwargs.pop("_agent_id", self._primary or "default-agent"),
                action=name, params=dict(kwargs),
                confidence=float(kwargs.get("confidence", 1.0) or 1.0),
            )
            verdict = self.engine.evaluate(env, self._agents.get(env.agent_id))
            if not verdict["allowed"]:
                return f"SAFR 检查点拦截（{verdict['disposition']}）：" + \
                       "；".join(verdict["reasons"])
            return None
        return _gate

    def audit_ok(self) -> bool:
        return self.audit.verify()


def default_twin() -> ComplianceTwin:
    """默认孪生：注册一个只读研究代理（研究场景，不做资金动作）。"""
    twin = ComplianceTwin(Controls(min_confidence=0.3, rate_max_calls=120))
    twin.register_agent(AgentIdentity(
        "research-agent", principal="local-user",
        capabilities={"fetch_stock_data", "calculate_indicators", "search_news",
                      "search_stocks", "get_market_overview", "run_backtest",
                      "chart_control", "read_visible_data", "chart_screenshot",
                      "get_realtime_snapshot", "run_screener", "get_drawings"},
        delegation_depth=0))
    return twin
