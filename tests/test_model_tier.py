# -*- coding: utf-8 -*-
"""模型层级分离（provider per model tier）测试。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("STOCKAI_MOCK", "1")


class TestTierMapping(unittest.TestCase):
    def test_role_tiers(self):
        from core.model_tier import tier_of_role
        self.assertEqual(tier_of_role("manager"), "flagship")
        self.assertEqual(tier_of_role("deep_research"), "flagship")
        self.assertEqual(tier_of_role("risk"), "flagship")
        self.assertEqual(tier_of_role("technical"), "balanced")
        self.assertEqual(tier_of_role("news"), "balanced")
        self.assertEqual(tier_of_role("compliance"), "lite")
        self.assertEqual(tier_of_role("不存在角色"), "balanced")  # 未知回退

    def test_platform_chain_no_duplicate_and_local_fallback(self):
        from core.model_tier import platforms_for_role
        for role in ("manager", "technical", "compliance"):
            plats = platforms_for_role(role)
            self.assertEqual(len(plats), len(set(plats)), f"{role} 链上平台重复")
            self.assertIn("ollama", plats, f"{role} 缺少本地兜底")

    def test_flagship_starts_with_fin_model(self):
        from core.model_tier import platforms_for_role
        self.assertEqual(platforms_for_role("manager")[0], "ling")

    def test_lite_prefers_local(self):
        from core.model_tier import TIER_PLATFORMS
        self.assertEqual(TIER_PLATFORMS["lite"][0], "ollama_fin")


class TestStatus(unittest.TestCase):
    def test_tier_status_structure(self):
        from core.model_tier import tier_status, role_table
        st = tier_status()
        self.assertEqual(set(st), {"flagship", "balanced", "lite"})
        for t, info in st.items():
            self.assertIn("label", info)
            self.assertIsInstance(info["available"], list)
        self.assertTrue(any(r["role"] == "manager" for r in role_table()))


class TestChatForRole(unittest.TestCase):
    def test_returns_tuple_and_degrades_safely(self):
        """无可用 key 时返回 (None, '', tier) 而不抛异常。"""
        from core.model_tier import chat_for_role
        txt, eng, tier = chat_for_role("compliance", "ping", timeout=2)
        self.assertIn(tier, ("lite", "balanced", "flagship"))
        self.assertIsInstance(eng, str)
        self.assertTrue(txt is None or isinstance(txt, str))

    def test_task_compat(self):
        from core.model_tier import chat_for_task
        txt, eng, tier = chat_for_task("risk", "ping", timeout=2)
        self.assertIn(tier, ("flagship", "balanced", "lite"))


class TestLazyClientAndMock(unittest.TestCase):
    def test_mock_chat_returns_stub_without_network(self):
        """STOCKAI_MOCK=1 下 chat() 短路网络、秒级返回确定串。"""
        from core import model_router as mr
        out = mr.chat("今天大盘如何", platform="deepseek", timeout=5)
        self.assertIsInstance(out, str)
        self.assertIn(mr._MOCK_REPLY, out)
        self.assertIn("deepseek", out)

    def test_lazy_client_cache_reuses_instance(self):
        """同一平台客户端惰性单例；不同平台不复用；clear 生效。"""
        from core import model_router as mr
        import inspect
        # _get_client 不触网，仅构造客户端对象
        c1 = mr._get_client("ollama", mr.PLATFORMS["ollama"], 10)
        c2 = mr._get_client("ollama", mr.PLATFORMS["ollama"], 10)
        self.assertIs(c1, c2, "同平台客户端应复用（惰性单例）")
        c3 = mr._get_client("deepseek", mr.PLATFORMS["deepseek"], 10)
        self.assertIsNot(c1, c3, "不同平台客户端应独立")
        n = mr._client_cache_clear()
        self.assertGreaterEqual(n, 2)
        # clear 后重新构造得到新实例
        c4 = mr._get_client("ollama", mr.PLATFORMS["ollama"], 10)
        self.assertIsNot(c1, c4)


if __name__ == "__main__":
    unittest.main(verbosity=2)
