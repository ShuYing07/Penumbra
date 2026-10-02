# -*- coding: utf-8 -*-
"""模型路由升级测试：任务类型路由 / 2026 平台目录 / 本地探测降级 / 推荐清单。"""
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("STOCKAI_MOCK", "1")

# 假 OpenAI 客户端：记录调用（base_url, model, max_tokens）
_FAKE_CALLS: list = []


class _FakeCompletions:
    def __init__(self, client):
        self._c = client

    def create(self, model, messages, temperature, max_tokens):
        _FAKE_CALLS.append((self._c.base_url, model, max_tokens))
        resp = types.SimpleNamespace(choices=[
            types.SimpleNamespace(message=types.SimpleNamespace(content="测试回复"))])
        return resp


class _FakeChat:
    def __init__(self, client):
        self._c = client

    @property
    def completions(self):
        return _FakeCompletions(self._c)


class _FakeOpenAI:
    def __init__(self, api_key, base_url, timeout):
        # 模拟真实行为：未配置 key 的平台调用必然失败（401）→ 自动降级
        if not api_key or api_key == "ollama":
            raise Exception("401 Unauthorized")
        self._c = types.SimpleNamespace(base_url=base_url, api_key=api_key)

    @property
    def chat(self):
        return _FakeChat(self._c)


class TestModelRouter2(unittest.TestCase):
    def setUp(self):
        _FAKE_CALLS.clear()
        sys.modules["openai"] = types.SimpleNamespace(OpenAI=_FakeOpenAI)

    def tearDown(self):
        sys.modules.pop("openai", None)

    def _set_keys(self, names):
        env_map = {"ling": "DEEPINFRA_API_KEY", "openrouter": "OPENROUTER_API_KEY",
                   "deepseekv4": "DEEPSEEK_API_KEY", "deepseek": "DEEPSEEK_API_KEY",
                   "qwen35": "QWEN_API_KEY", "glm": "GLM_API_KEY"}
        for k in env_map.values():
            os.environ.pop(k, None)
        for n in names:
            os.environ[env_map[n]] = "test-key"

    def test_finance_report_routes_ling_first(self):
        from core import model_router
        self._set_keys(["ling", "deepseek"])
        content, engine = model_router.chat_for(
            "finance_report", "分析贵州茅台2025年报", system="你是金融分析师")
        self.assertEqual(engine, "ling")
        self.assertEqual(content, "测试回复")
        # 金融任务 max_tokens 更大
        self.assertGreater(_FAKE_CALLS[0][2], 1024)

    def test_finance_falls_back_when_no_ling_key(self):
        from core import model_router
        self._set_keys(["deepseek"])
        _, engine = model_router.chat_for("valuation", "估值茅台")
        # deepseekv4 / deepseek 共用 DEEPSEEK_API_KEY，v4 更优先
        self.assertIn(engine, ("deepseek", "deepseekv4"))

    def test_general_uses_deepseek_first(self):
        from core import model_router
        self._set_keys(["ling", "deepseek"])
        _, engine = model_router.chat_for("general", "你好")
        self.assertIn(engine, ("deepseek", "deepseekv4"))

    def test_all_cloud_fail_returns_none(self):
        from core import model_router
        # 无任何云端 key；同时屏蔽本地平台（避免本机 Ollama 干扰断言）
        self._set_keys([])
        saved = model_router.PLATFORMS
        model_router.PLATFORMS = {k: v for k, v in saved.items()
                                  if v["key_env"] is not None}
        try:
            content, engine = model_router.chat_for("finance_report", "测试")
            self.assertIsNone(content)
            self.assertEqual(engine, "")
        finally:
            model_router.PLATFORMS = saved

    def test_platform_catalog_has_2026_models(self):
        from core import model_router
        names = set(model_router.PLATFORMS)
        self.assertIn("ling", names)
        self.assertIn("openrouter", names)
        self.assertIn("deepseekv4", names)
        self.assertIn("qwen35", names)
        self.assertIn("ollama_fin", names)
        self.assertIn("ling-3.0-flash-fin",
                      model_router.PLATFORMS["ling"]["model"].lower())
        self.assertIn("deepseek-v4",
                      model_router.PLATFORMS["deepseekv4"]["model"].lower())

    def test_recommended_list_has_finance_models(self):
        from core import model_router
        rec = model_router.recommended_local_models()
        names = [m["name"] for m in rec]
        self.assertIn("ling-3.0-flash-fin", names)
        self.assertIn("qwen3:14b", names)
        for m in rec:
            self.assertIn("pull", m)
            self.assertTrue(m["pull"].startswith("ollama pull"))

    def test_engine_status_shape(self):
        from core import model_router
        st = model_router.engine_status()
        for k in ("cloud_ready", "local_installed", "recommended_missing",
                  "ollama_running"):
            self.assertIn(k, st)
        self.assertIsInstance(st["cloud_ready"], list)

    def test_ollama_fin_resolve_degraded(self):
        from core import model_router
        # 探测永不抛异常；返回 str（本机有 Ollama 时返回探测结果）或 None
        r = model_router._resolve_ollama_fin_model()
        self.assertTrue(r is None or isinstance(r, str))


if __name__ == "__main__":
    unittest.main(verbosity=2)
