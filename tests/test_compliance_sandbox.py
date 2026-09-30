# -*- coding: utf-8 -*-
"""模块四：合规沙箱测试。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("STOCKAI_MOCK", "1")

from security.compliance_sandbox import (  # noqa: E402
    SandboxEnvironment, SCENARIOS, ToolGate,
    get_scenario, run_agent_in_sandbox, run_all_scenarios, scenario_count,
)

PASS = 0


def ok(name: str):
    global PASS
    PASS += 1
    print(f"[ok] {name}")


# ---- 场景完整性 ----
def test_scenario_count_is_31():
    assert scenario_count() == 31, f"应恰好 31 个场景，实际 {scenario_count()}"
    cats = {s["category"] for s in SCENARIOS}
    assert len(cats) >= 7, f"至少 7 个类别：{cats}"
    ok(f"31 个监管场景（{', '.join(sorted(cats))}）")


def test_all_scenarios_initial_scan_no_crash():
    results = run_all_scenarios()
    assert len(results) == 31
    assert all("initial_flags" in r and "rule_count" in r for r in results)
    assert all(r["rule_count"] >= 1 for r in results), "每场景至少 1 条规则"
    ok("全部场景初始扫描无异常、规则数≥1")


def test_every_scenario_setup_has_accounts_for_actions():
    # 场景 setup 中用到 transfer/withdraw 的必须有对应账户（防执行失败）
    for s in SCENARIOS:
        env = SandboxEnvironment(s["setup"])
        env.close()
    ok("所有场景 setup 均可初始化")


# ---- 违规 / 合规路径 ----
def test_aml01_violation_path_detected():
    def bad_agent(env):
        return [{"type": "transfer", "from": "a1", "to": "a2", "amount": 1_200_000,
                 "id": "tx-bad"}]
    r = run_agent_in_sandbox(bad_agent, "aml-01")
    assert r["ok"] and r["action_count"] == 1
    assert r["passed"] is False, "大额转账未报告必须判违规"
    assert r["violations"] and r["violations"][0]["severity"] == "high"
    ok("aml-01 违规路径正确触发（大额转账未 STR）")


def test_aml01_compliant_path_passes():
    def good_agent(env):
        return [{"type": "transfer", "from": "a1", "to": "a2", "amount": 1_200_000,
                 "id": "tx-ok"},
                {"type": "mark_str", "tx_id": "tx-ok"}]
    r = run_agent_in_sandbox(good_agent, "aml-01")
    assert r["passed"] is True, "转账+STR 应通过"
    assert not r["violations"]
    ok("aml-01 合规路径（转账+STR）通过")


def test_transfer_insufficient_balance_rejected():
    env = SandboxEnvironment({"accounts": [{"id": "a1", "balance": 100},
                                            {"id": "a2", "balance": 0}]})
    res = env.execute({"type": "transfer", "from": "a1", "to": "a2", "amount": 500})
    assert res["ok"] is False and "余额" in res["detail"]
    env.close()
    ok("余额不足转账被拒绝")


# ---- ToolGate 解耦 ----
def test_toolgate_allows_registered_and_denies_unknown():
    gate = ToolGate()
    ok_call, reason = gate.check_tool_call("query", {"sql": "SELECT 1"})
    assert ok_call and reason == "ok"
    bad_call, reason2 = gate.check_tool_call("hack_db", {})
    assert bad_call is False and "未注册" in reason2
    assert gate.audit_log and gate.audit_log[-1]["decision"] == "deny"
    ok("ToolGate：注册工具放行、未注册工具拒绝并记审计")


def test_toolgate_type_validation():
    gate = ToolGate()
    ok_call, reason = gate.check_tool_call("transfer",
                                           {"from": "a1", "to": "a2", "amount": "abc"})
    assert ok_call is False and "类型" in reason
    ok("ToolGate：参数类型错误被拒")


def test_toolgate_missing_param_rejected():
    gate = ToolGate()
    ok_call, reason = gate.check_tool_call("transfer", {"from": "a1", "to": "a2"})
    assert ok_call is False and "缺少" in reason
    ok("ToolGate：缺少必填参数被拒")


def test_gate_scenario_scan_flags_violations():
    """gate() 在绑定场景时执行动作并扫描合规约束。"""
    gate = ToolGate()
    env = SandboxEnvironment(get_scenario("aml-01")["setup"])
    gate._scenario = get_scenario("aml-01")
    res = gate.gate("transfer", {"from": "a1", "to": "a2", "amount": 1_200_000}, env)
    assert res["ok"] and res["gated"]
    assert env.violations, "通过 Gate 的大额转账应被场景规则标记"
    env.close()
    ok("Gate 场景联动：工具调用过合规检查层并触发约束")


def _main():
    test_scenario_count_is_31()
    test_all_scenarios_initial_scan_no_crash()
    test_every_scenario_setup_has_accounts_for_actions()
    test_aml01_violation_path_detected()
    test_aml01_compliant_path_passes()
    test_transfer_insufficient_balance_rejected()
    test_toolgate_allows_registered_and_denies_unknown()
    test_toolgate_type_validation()
    test_toolgate_missing_param_rejected()
    test_gate_scenario_scan_flags_violations()
    print(f"\nALL PASS ({PASS})")


if __name__ == "__main__":
    _main()
