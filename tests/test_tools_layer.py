# -*- coding: utf-8 -*-
"""模块一 · AI Agent 工具调用层 单元测试。

覆盖：统一信封契约 / Schema 生成 / 注册表调用链 / 治理前置钩子 /
      图表 AI 控制面状态一致性 / MCP JSON-RPC 端点 / 向后兼容性。

离线可跑：只依赖本地股票索引与图表引擎，不触网。
运行：venv\Scripts\python.exe -B tests\test_tools_layer.py
"""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("STOCKAI_MOCK", "1")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tools import ToolResult, get_registry  # noqa: E402
from tools.base import RiskLevel, ToolError  # noqa: E402


class TestToolResult(unittest.TestCase):
    """统一信封 {success, data, error, meta}。"""

    def test_success_alias_and_envelope(self):
        r = ToolResult.succeed("demo", {"a": 1}, note="说明", source="test")
        self.assertTrue(r.ok)
        self.assertTrue(r.success)           # 新契约别名
        self.assertEqual(r.error, "")
        env = r.to_envelope()
        self.assertEqual(set(env.keys()), {"success", "data", "error", "meta"})
        self.assertTrue(env["success"])
        self.assertEqual(env["meta"]["source"], "test")

    def test_failed_has_readable_error(self):
        r = ToolResult.failed("demo", "参数不能为空")
        self.assertFalse(r.ok)
        self.assertFalse(r.success)
        self.assertIn("参数不能为空", r.error)
        self.assertIsNone(r.data)

    def test_to_text_truncates_long_payload(self):
        r = ToolResult.succeed("demo", {"blob": "x" * 5000})
        txt = r.to_text(max_chars=100)
        self.assertLess(len(txt), 300)
        self.assertIn("已截断", txt)

    def test_success_property_mirrors_ok(self):
        r = ToolResult(ok=False, tool="t")
        self.assertFalse(r.success)


class TestRegistry(unittest.TestCase):
    """注册表：Schema、调用链、参数校验、风险分级。"""

    def setUp(self):
        self.reg = get_registry()

    def test_tools_registered_with_category_and_risk(self):
        names = self.reg.names()
        self.assertGreaterEqual(len(names), 10)
        for n in names:
            spec = self.reg.get(n)
            self.assertIsNotNone(spec, n)
            self.assertTrue(spec.description.strip(), f"{n} 缺少描述")
            self.assertIn(spec.category, {"market", "analysis", "chart", "general"})
            self.assertIsInstance(spec.risk, RiskLevel)

    def test_parameters_schema_is_json_schema(self):
        spec = self.reg.get("fetch_stock_data")
        schema = spec.parameters_schema
        self.assertEqual(schema["type"], "object")
        self.assertIn("code", schema["properties"])
        self.assertIn("code", schema.get("required", []))

    def test_mcp_and_openai_tool_shapes(self):
        mcp = self.reg.mcp_tools()
        self.assertTrue(all({"name", "description", "inputSchema"} <= set(t) for t in mcp))
        oa = self.reg.openai_tools()
        self.assertTrue(all(t["type"] == "function" for t in oa))
        self.assertTrue(all("parameters" in t["function"] for t in oa))

    def test_unknown_tool_returns_failed_envelope(self):
        r = self.reg.call("绝对不存在的工具", {})
        self.assertFalse(r.ok)
        self.assertIn("未知工具", r.error)
        self.assertIn("可用工具", r.note)      # 失败也要给出可自纠的提示

    def test_param_validation_error_is_readable(self):
        r = self.reg.call("search_news", {"code": "SH600519", "limit": 9999})
        self.assertFalse(r.ok)
        self.assertIn("参数校验失败", r.error)

    def test_call_succeeds_and_records_meta(self):
        r = self.reg.call("search_stocks", {"query": "茅台", "limit": 3})
        self.assertTrue(r.ok, r.error)
        self.assertIn("latency_ms", r.meta)
        self.assertIn("source", r.meta)
        self.assertEqual(r.meta["risk"], "read_only")
        self.assertIn("SH600519", str(r.data))

    def test_exception_never_escapes_call(self):
        """任何异常都必须被收进信封，绝不把栈抛给 LLM。"""
        import logging

        def boom():
            raise RuntimeError("内部炸了")

        from tools.base import ToolSpec
        self.reg.register(ToolSpec(name="_boom_test", description="测试", func=boom))
        # 注册表会 log.exception 留痕；本用例刻意制造异常，临时静音避免污染输出
        lg = logging.getLogger("stockai.tools")
        old = lg.level
        lg.setLevel(logging.CRITICAL)
        try:
            r = self.reg.call("_boom_test", {})
        finally:
            lg.setLevel(old)
        self.assertFalse(r.ok)
        self.assertIn("内部炸了", r.error)

    def test_tool_error_carries_hint(self):
        from tools.base import ToolSpec

        def raise_tool_error():
            raise ToolError("缺参数", hint="试试传 code")

        self.reg.register(ToolSpec(name="_hinter", description="测试", func=raise_tool_error))
        r = self.reg.call("_hinter", {})
        self.assertFalse(r.ok)
        self.assertIn("缺参数", r.error)
        self.assertIn("试试传 code", r.note)


class TestGovernanceHook(unittest.TestCase):
    """SAFR 风格治理检查点：调用前拦截。"""

    def test_pre_hook_can_block_call(self):
        reg = get_registry()
        calls = []

        def gate(name, kwargs):
            calls.append(name)
            return "超出授权范围" if name == "run_backtest" else None

        reg.add_pre_hook(gate)
        try:
            blocked = reg.call("run_backtest", {"code": "SH600519"})
            self.assertFalse(blocked.ok)
            self.assertIn("超出授权范围", blocked.error)
            self.assertEqual(blocked.note, "被治理检查点拦截")
            allowed = reg.call("search_stocks", {"query": "茅台", "limit": 1})
            self.assertTrue(allowed.ok)
            self.assertIn("run_backtest", calls)
        finally:
            reg._pre_hooks = [h for h in reg._pre_hooks if h is not gate]

    def test_broken_hook_does_not_break_chain(self):
        """钩子自身异常不得阻断调用链（治理失效也要保证可用性）。"""
        reg = get_registry()

        def bad_hook(name, kwargs):
            raise RuntimeError("钩子挂了")

        reg.add_pre_hook(bad_hook)
        try:
            r = reg.call("search_stocks", {"query": "茅台", "limit": 1})
            self.assertTrue(r.ok)
        finally:
            reg._pre_hooks = [h for h in reg._pre_hooks if h is not bad_hook]

    def test_post_hook_receives_result(self):
        reg = get_registry()
        seen = []
        reg.add_post_hook(lambda res: seen.append(res.tool))
        try:
            reg.call("search_stocks", {"query": "茅台", "limit": 1})
            self.assertIn("search_stocks", seen)
        finally:
            reg._post_hooks = []


class TestChartControlPlane(unittest.TestCase):
    """图表 AI 控制面：控制与快照必须看到同一份状态。"""

    def test_add_indicator_then_snapshot(self):
        reg = get_registry()
        r1 = reg.call("chart_control", {"ticker": "SH600519", "action": "reset"})
        self.assertTrue(r1.ok, r1.error)
        r2 = reg.call("chart_control", {"ticker": "SH600519", "action": "add_indicator",
                                        "id": "MA60", "params": {"n": 60}})
        self.assertTrue(r2.ok, r2.error)
        snap = reg.call("chart_screenshot", {"ticker": "SH600519"})
        self.assertTrue(snap.ok, snap.error)
        ids = [i["id"] for i in snap.data["indicators"]]
        self.assertIn("MA60", ids)
        self.assertEqual(snap.data["indicator_count"], len(snap.data["indicators"]))

    def test_read_visible_data_requires_ticker(self):
        reg = get_registry()
        r = reg.call("read_visible_data", {})
        self.assertFalse(r.ok)
        self.assertIn("标的代码", r.error)


class TestMcpEndpoint(unittest.TestCase):
    """MCP JSON-RPC 端点（stdio/HTTP 共用同一处理函数）。"""

    def setUp(self):
        from agent.mcp_server import handle_request
        self.handle = handle_request

    def test_initialize(self):
        resp = self.handle({"id": 1, "method": "initialize"})
        self.assertEqual(resp["result"]["protocolVersion"], "2025-06-18")
        self.assertIn("tools", resp["result"]["capabilities"])

    def test_tools_list_contract(self):
        resp = self.handle({"id": 2, "method": "tools/list"})
        tools = resp["result"]["tools"]
        self.assertGreaterEqual(len(tools), 10)
        for t in tools:
            self.assertTrue(t["name"])
            self.assertIn("inputSchema", t)

    def test_tools_call_returns_structured_content(self):
        resp = self.handle({"id": 3, "method": "tools/call",
                            "params": {"name": "search_stocks",
                                       "arguments": {"query": "茅台", "limit": 2}}})
        res = resp["result"]
        self.assertFalse(res["isError"])
        self.assertIn("success", res["structuredContent"])
        self.assertEqual(res["content"][0]["type"], "text")

    def test_tools_call_error_flags_is_error(self):
        resp = self.handle({"id": 4, "method": "tools/call",
                            "params": {"name": "不存在的工具", "arguments": {}}})
        self.assertTrue(resp["result"]["isError"])

    def test_unknown_method_and_ping(self):
        resp = self.handle({"id": 5, "method": "nope"})
        self.assertEqual(resp["error"]["code"], -32601)
        self.assertEqual(self.handle({"id": 6, "method": "ping"})["result"], {})

    def test_notification_returns_none(self):
        self.assertIsNone(self.handle({"method": "notifications/initialized"}))


class TestBackwardCompat(unittest.TestCase):
    """既有调用方（agent.tool_defs / agent_core）不得被重构破坏。"""

    def test_agent_schemas_reexport(self):
        from agent.schemas import ToolResult as OldTR, ok_result, fail_result
        self.assertIs(OldTR, ToolResult)
        r = ok_result("t", {"x": 1})
        self.assertTrue(r.ok)
        f = fail_result("t", "炸了")
        self.assertFalse(f.ok)
        self.assertIn("炸了", f.note)   # 旧行为：失败信息也进 note

    def test_legacy_call_tool_still_works(self):
        from agent.tool_defs import build_registry, call_tool
        reg = build_registry()
        self.assertIn("fetch_stock_data", reg)
        r = call_tool("search_stocks", {"query": "茅台", "limit": 1})
        self.assertTrue(r.ok)

    def test_registry_stats_counting(self):
        reg = get_registry()
        before = reg.stats().get("search_stocks", 0)
        reg.call("search_stocks", {"query": "茅台", "limit": 1})
        self.assertEqual(reg.stats().get("search_stocks", 0), before + 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
    print("ALL PASS")
