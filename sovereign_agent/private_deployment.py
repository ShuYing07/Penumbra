# -*- coding: utf-8 -*-
"""私有化部署模式：数据不出企业边界。"""
from __future__ import annotations

import logging
import time
from enum import Enum

log = logging.getLogger("stockai.sovereign.deployment")


class DeploymentMode(str, Enum):
    LOCAL = "local"    # 全部在本机/内网
    SAAS = "saas"      # 托管云端
    HYBRID = "hybrid"  # 核心数据本地，计算云端


class PrivateDeployment:
    """私有化部署控制器。

    - mode=local：所有 Agent 在本机运行，出域数据（外发 token 文本/请求）被拦截记录；
    - mode=hybrid：允许出域计算，但敏感字段（如用户自选/持仓）禁止外发；
    - 每次 Agent 运行记录边界状态，供审计。
    """

    def __init__(self, mode: DeploymentMode = DeploymentMode.LOCAL,
                 sensitive_fields: tuple = ("portfolio", "positions", "watchlist")):
        self.mode = DeploymentMode(mode)
        self.sensitive_fields = sensitive_fields
        self._egress_log: list[dict] = []
        self._blocked = 0

    def set_mode(self, mode) -> None:
        self.mode = DeploymentMode(mode)

    def allow_egress(self, payload: dict) -> bool:
        """数据出域判定：saas 全放行；local 全拦截；hybrid 拦截敏感字段。"""
        if self.mode == DeploymentMode.SAAS:
            return True
        if self.mode == DeploymentMode.LOCAL:
            self._blocked += 1
            self._log("blocked", payload)
            return False
        # hybrid：非敏感字段可出域
        leaked = [k for k in payload if k in self.sensitive_fields]
        if leaked:
            self._blocked += 1
            self._log("blocked-sensitive", payload, note=f"字段: {','.join(leaked)}")
            return False
        self._log("allowed", payload)
        return True

    def run_agent(self, agent_name: str, fn, payload: dict) -> dict:
        """在边界策略下运行 Agent。local 模式下拒绝外部推理（演示语义）。"""
        if self.mode == DeploymentMode.LOCAL and payload.get("external_llm"):
            self._blocked += 1
            self._log("blocked", payload, note=f"agent={agent_name} 请求外部LLM")
            return {"ok": False, "reason": "local 模式禁止外部推理，请配置本地模型"}
        result = fn(payload) if callable(fn) else payload
        self._log("run", {"agent": agent_name})
        return {"ok": True, "result": result}

    def _log(self, kind: str, payload: dict, note: str = "") -> None:
        self._egress_log.append({"ts": time.time(), "kind": kind,
                                 "payload_keys": list(payload.keys()), "note": note})

    def stats(self) -> dict:
        return {"mode": self.mode.value, "blocked": self._blocked,
                "egress_log": len(self._egress_log)}


if __name__ == "__main__":
    d = PrivateDeployment(DeploymentMode.LOCAL)
    assert not d.allow_egress({"portfolio": {"x": 1}})
    assert not d.allow_egress({"query": "分析"})
    d.set_mode(DeploymentMode.HYBRID)
    assert not d.allow_egress({"portfolio": {}})      # 敏感字段拦截
    assert d.allow_egress({"query": "分析"})           # 非敏感放行
    d.set_mode(DeploymentMode.LOCAL)
    r = d.run_agent("analyst", None, {"external_llm": True})
    assert not r["ok"] and "local" in r["reason"]
    d.set_mode(DeploymentMode.SAAS)
    assert d.allow_egress({"portfolio": {}})
    print(f"PASS private_deployment 自测 {d.stats()}")
