# -*- coding: utf-8 -*-
"""本地金融知识蒸馏引擎测试：种子幂等 / 检索排序 / 领域过滤 / 上下文注入。"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("STOCKAI_MOCK", "1")


class _KDCase(unittest.TestCase):
    def _kd(self, td):
        from core.knowledge_distiller import KnowledgeDistiller
        return KnowledgeDistiller(Path(td) / "kb.db")


class TestSeed(_KDCase):
    def test_seed_idempotent(self):
        from core.distilled_knowledge import KNOWLEDGE
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            kd = self._kd(td)
            self.assertEqual(kd.seed(), len(KNOWLEDGE))
            self.assertEqual(kd.seed(force=True), len(KNOWLEDGE))  # 不重复
            self.assertEqual(kd.count(), len(KNOWLEDGE))

    def test_knowledge_data_integrity(self):
        from core.distilled_knowledge import KNOWLEDGE, DOMAINS
        self.assertGreaterEqual(len(KNOWLEDGE), 50)   # 蒸馏规模下限
        self.assertGreaterEqual(len(DOMAINS), 14)     # 领域覆盖下限
        for k in KNOWLEDGE:
            self.assertIn(k["domain"], DOMAINS)
            for f in ("topic", "title", "principle", "application", "caveat"):
                self.assertTrue(k.get(f), f"{k.get('title')} 缺 {f}")
        # 无重复
        keys = [(k["domain"], k["title"]) for k in KNOWLEDGE]
        self.assertEqual(len(keys), len(set(keys)))


class TestSearch(_KDCase):
    def test_relevance_ranking(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            kd = self._kd(td)
            hits = kd.search("美联储 利率 成长股 估值")
            self.assertTrue(hits)
            # 标题命中应排在正文命中之前（relevance 递减）
            rels = [h["relevance"] for h in hits]
            self.assertEqual(rels, sorted(rels, reverse=True))

    def test_domain_filter(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            kd = self._kd(td)
            hits = kd.search("过拟合 多重检验", domain="数学工具")
            self.assertTrue(hits)
            self.assertTrue(all(h["domain"] == "数学工具" for h in hits))

    def test_empty_and_noisy_query(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            kd = self._kd(td)
            self.assertEqual(kd.search(""), [])
            self.assertEqual(kd.search("的 了 与"), [])


class TestContextInjection(_KDCase):
    def test_build_context_format(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            kd = self._kd(td)
            ctx = kd.build_context("如何识别财务造假", limit=2)
            self.assertIn("【本地蒸馏知识参考】", ctx)
            self.assertIn("边界", ctx)          # 必含边界提醒
            self.assertIn("非投资建议", ctx)      # 合规声明

    def test_context_length_cap(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            kd = self._kd(td)
            ctx = kd.build_context("估值", limit=5, max_chars=400)
            self.assertLessEqual(len(ctx), 800)  # 截断生效（允许单块溢出余量）

    def test_no_hit_returns_empty(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            kd = self._kd(td)
            # 纯乱码 token，与任何条目无交集
            self.assertEqual(kd.build_context("zzzqqq xyzvbn"), "")


class TestCustomKnowledge(_KDCase):
    def test_add_and_dedup(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            kd = self._kd(td)
            self.assertTrue(kd.add_knowledge(
                "风险管理", "自研", "自定义条目A", "原理", "应用", "边界", ["t"]))
            self.assertFalse(kd.add_knowledge(
                "风险管理", "自研", "自定义条目A", "原理", "应用", "边界"))
            self.assertEqual(kd.stats()["custom"], 1)
            hits = kd.search("自定义条目A")
            self.assertTrue(hits)
            self.assertEqual(hits[0]["source"], "custom")

    def test_unknown_domain_rejected(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            kd = self._kd(td)
            with self.assertRaises(ValueError):
                kd.add_knowledge("不存在的领域", "t", "t", "p", "a", "c")


if __name__ == "__main__":
    unittest.main(verbosity=2)
