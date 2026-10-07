# -*- coding: utf-8 -*-
"""InKH 交互原生知识装配测试：单次检索 / 新鲜度门控 / 预算强制。"""
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("STOCKAI_MOCK", "1")


class _Case(unittest.TestCase):
    def _harness(self, td):
        from core.knowledge_distiller import KnowledgeDistiller
        from core.knowledge_harness import KnowledgeHarness
        return KnowledgeHarness(KnowledgeDistiller(Path(td) / "kb.db"))


class TestSinglePassRetrieval(_Case):
    def test_retrieve_enriched(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            h = self._harness(td)
            items = h.retrieve("美联储 利率 估值")
            self.assertTrue(items)
            for i in items:
                self.assertIn("freshness", i)
                self.assertIn("score", i)
            st = h.stats()
            self.assertTrue(st["single_pass"])
            self.assertLess(st["latency_ms"], 200)  # 单次检索应毫秒级


class TestFreshnessGating(_Case):
    def test_stale_items_flagged_and_downweighted(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            from core.knowledge_distiller import KnowledgeDistiller
            from core.knowledge_harness import KnowledgeHarness
            kd = KnowledgeDistiller(Path(td) / "kb.db")
            kd.seed()
            h = KnowledgeHarness(kd, max_items=5)
            fresh = [i for i in h.retrieve("多重检验") if not i["freshness"]["stale"]]
            self.assertTrue(fresh)
            # 把相关条目时间改到 10 年前 → 应被标记陈旧
            with kd._connect() as con:
                con.execute(
                    "UPDATE knowledge SET created_ts=? WHERE domain='数学工具'",
                    (time.time() - 3650 * 86400,))
                con.commit()
            old = h.retrieve("多重检验", limit=5)
            self.assertTrue(any(i["freshness"]["stale"] for i in old))
            # 降权口径：同一条目的 score 必须 = 相关度 × 陈旧权重
            for i in old:
                if i["freshness"]["stale"]:
                    self.assertAlmostEqual(
                        i["score"],
                        round(float(i.get("relevance") or 1.0) * h.stale_weight, 4),
                        places=3)
                else:
                    self.assertAlmostEqual(
                        i["score"], round(float(i.get("relevance") or 1.0), 4),
                        places=3)


class TestBudget(_Case):
    def test_context_within_budget(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            h = self._harness(td)
            ctx = h.build_context("回测 过拟合", max_chars=400)
            if ctx:
                self.assertLessEqual(len(ctx), 900)
                self.assertTrue(ctx.startswith("【本地知识参考·单次检索】"))
                self.assertGreater(h.stats()["tokens_est"], 0)

    def test_empty_query_returns_empty(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            h = self._harness(td)
            self.assertEqual(h.build_context("zzzqqq vvv"), "")


class TestTokenEstimate(unittest.TestCase):
    def test_estimate(self):
        from core.knowledge_harness import KnowledgeHarness
        t = KnowledgeHarness.estimate_tokens("估值方法很重要 Valuation")
        self.assertGreater(t, 0)
        self.assertGreater(KnowledgeHarness.estimate_tokens("中文中文中文"),
                           KnowledgeHarness.estimate_tokens("ab"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
