# -*- coding: utf-8 -*-
"""合规数字孪生 + SAFR 治理检查点 单元测试。"""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("STOCKAI_MOCK", "1")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from security.compliance_twin import (  # noqa: E402
    AUTO_EXECUTE, DENY, ESCALATE, OBSERVE, AgentIdentity, ComplianceTwin,
    Controls, DispositionEngine, GovernanceEnvelope, TamperEvidentLog,
    default_twin)


def _twin() -> ComplianceTwin:
    t = ComplianceTwin(Controls(min_confidence=0.3, rate_max_calls=50))
    t.register_agent(AgentIdentity("agent-1", principal="user",
                                   capabilities={"query", "analyze"}))
    return t


class TestIdentity(unittest.TestCase):
    def test_capability_check(self):
        a = AgentIdentity("a", capabilities={"query"})
        self.assertTrue(a.may("query"))
        self.assertFalse(a.may("transfer"))

    def test_empty_capabilities_means_unrestricted(self):
        self.assertTrue(AgentIdentity("a").may("anything"))

    def test_unregistered_agent_denied(self):
        t = _twin()
        v = t.simulate(GovernanceEnvelope("陌生人", "query"))["verdict"]
        self.assertEqual(v["disposition"], DENY)
        self.assertFalse(v["allowed"])


class TestDispositions(unittest.TestCase):
    def setUp(self):
        self.t = _twin()

    def test_auto_execute_within_authority(self):
        v = self.t.simulate(GovernanceEnvelope("agent-1", "query", confidence=0.9))["verdict"]
        self.assertEqual(v["disposition"], AUTO_EXECUTE)
        self.assertTrue(v["allowed"])

    def test_deny_when_outside_authority(self):
        v = self.t.simulate(GovernanceEnvelope("agent-1", "transfer", value=1e6))["verdict"]
        self.assertEqual(v["disposition"], DENY)

    def test_escalate_on_low_confidence(self):
        v = self.t.simulate(GovernanceEnvelope("agent-1", "query", confidence=0.05))["verdict"]
        self.assertEqual(v["disposition"], ESCALATE)
        self.assertFalse(v["allowed"])

    def test_escalate_when_evidence_required_but_missing(self):
        t = ComplianceTwin(Controls(require_evidence=True, min_confidence=0.0))
        t.register_agent(AgentIdentity("a", capabilities={"x"}))
        v = t.simulate(GovernanceEnvelope("a", "x"))["verdict"]
        self.assertEqual(v["disposition"], ESCALATE)
        self.assertTrue(any("证据" in r for r in v["reasons"]))

    def test_observe_for_irreversible_action(self):
        v = self.t.simulate(GovernanceEnvelope(
            "agent-1", "query", reversible=False))["verdict"]
        self.assertEqual(v["disposition"], OBSERVE)
        self.assertTrue(v["allowed"])      # observe 允许执行但留痕

    def test_observe_for_regulatory_sensitive(self):
        v = self.t.simulate(GovernanceEnvelope(
            "agent-1", "query", regulatory_sensitive=True))["verdict"]
        self.assertEqual(v["disposition"], OBSERVE)

    def test_exposure_limit_escalates(self):
        t = ComplianceTwin(Controls(exposure_per_action={"trade": 1000.0},
                                    min_confidence=0.0))
        t.register_agent(AgentIdentity("a", capabilities={"trade"}))
        v = t.simulate(GovernanceEnvelope("a", "trade", value=5000.0))["verdict"]
        self.assertEqual(v["disposition"], ESCALATE)

    def test_rate_limit_denies(self):
        t = ComplianceTwin(Controls(rate_max_calls=2, rate_window_s=60,
                                    min_confidence=0.0))
        t.register_agent(AgentIdentity("a", capabilities={"q"}))
        for _ in range(3):
            v = t.simulate(GovernanceEnvelope("a", "q"))["verdict"]
        self.assertEqual(v["disposition"], DENY)
        self.assertTrue(any("频次" in r for r in v["reasons"]))


class TestTwinExecution(unittest.TestCase):
    def test_allowed_action_executes(self):
        t = _twin()
        r = t.execute(GovernanceEnvelope("agent-1", "query", confidence=0.9),
                      lambda e: {"rows": 10})
        self.assertTrue(r["executed"])
        self.assertEqual(r["result"], {"rows": 10})

    def test_blocked_action_never_executes(self):
        t = _twin()
        calls = []
        r = t.execute(GovernanceEnvelope("agent-1", "wire_money"),
                      lambda e: calls.append(1))
        self.assertFalse(r["executed"])
        self.assertEqual(calls, [])
        self.assertTrue(r["blocked_reason"])

    def test_executor_exception_is_captured(self):
        t = _twin()

        def boom(_):
            raise RuntimeError("下游炸了")

        r = t.execute(GovernanceEnvelope("agent-1", "query", confidence=0.9), boom)
        self.assertFalse(r["executed"])
        self.assertIn("RuntimeError", r["error"])

    def test_simulation_has_no_side_effects(self):
        t = _twin()
        sim = t.simulate(GovernanceEnvelope("agent-1", "query"))
        self.assertTrue(sim["dry_run"])
        self.assertEqual(sim["side_effects"], [])

    def test_judge_can_escalate(self):
        """注入的语义评估器能否决原本自动执行的动作。"""
        t = ComplianceTwin(Controls(min_confidence=0.0),
                           judge=lambda e: (False, "措辞含收益承诺"))
        t.register_agent(AgentIdentity("a", capabilities={"q"}))
        v = t.simulate(GovernanceEnvelope("a", "q"))["verdict"]
        self.assertEqual(v["disposition"], ESCALATE)
        self.assertTrue(any("孪生评估" in r for r in v["reasons"]))

    def test_broken_judge_is_ignored(self):
        def bad(_):
            raise RuntimeError("评审器挂了")

        t = ComplianceTwin(Controls(min_confidence=0.0), judge=bad)
        t.register_agent(AgentIdentity("a", capabilities={"q"}))
        v = t.simulate(GovernanceEnvelope("a", "q"))["verdict"]
        self.assertTrue(v["allowed"])


class TestAuditLog(unittest.TestCase):
    def test_hash_chain_verifies(self):
        lg = TamperEvidentLog()
        lg.append("a", {"x": 1})
        lg.append("b", {"y": 2})
        self.assertTrue(lg.verify())
        self.assertEqual(len(lg), 2)

    def test_tampering_detected(self):
        lg = TamperEvidentLog()
        lg.append("a", {"x": 1})
        lg.append("b", {"y": 2})
        lg.records()[0]["payload"]["x"] = 999      # 篡改首条
        self.assertFalse(lg.verify())

    def test_twin_audit_chain_intact(self):
        t = _twin()
        t.execute(GovernanceEnvelope("agent-1", "query", confidence=0.9), lambda e: 1)
        self.assertTrue(t.audit_ok())
        self.assertGreater(len(t.audit), 1)


class TestToolGateIntegration(unittest.TestCase):
    def test_gate_blocks_unauthorized_tool(self):
        t = _twin()
        gate = t.gate_for_tools()
        self.assertIsNone(gate("query", {"q": 1}))         # 授权内 → 放行
        self.assertIsNotNone(gate("drop_database", {}))    # 超范围 → 拦截

    def test_gate_message_is_readable(self):
        t = _twin()
        msg = t.gate_for_tools()("drop_database", {})
        self.assertIn("SAFR", msg)
        self.assertIn("拦截", msg)

    def test_default_twin_allows_research_tools(self):
        t = default_twin()
        gate = t.gate_for_tools()
        for tool in ("fetch_stock_data", "calculate_indicators", "chart_control"):
            self.assertIsNone(gate(tool, {}), f"{tool} 应被放行")


if __name__ == "__main__":
    unittest.main(verbosity=2)
    print("ALL PASS")
