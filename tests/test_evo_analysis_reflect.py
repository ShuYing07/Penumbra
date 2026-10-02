# -*- coding: utf-8 -*-
"""分析级反思（自主学习闭环）测试：analyze_reflect 入库 + analysis_lessons 聚合。"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("STOCKAI_MOCK", "1")
# 隔离 DB：独立缓存目录，避免污染真实进化记忆
_tmp = tempfile.mkdtemp(prefix="evo_test_")
os.environ["STOCKAI_CACHE_DIR"] = _tmp

from core.agents import evo_memory  # noqa: E402


class TestAnalyzeReflect(unittest.TestCase):
    def setUp(self):
        # 清空分析反思表（保留表结构）
        import sqlite3
        with evo_memory._db() as c:
            c.execute("DELETE FROM evo_analysis_reflections")

    def test_high_confidence_lesson(self):
        r = evo_memory.analyze_reflect(
            {"kind": "财报", "ticker": "600519", "verdict": "看多",
             "confidence": 0.85, "model_engine": "ling"})
        self.assertIn("高置信", r["lesson"])
        self.assertEqual(r["verdict"], "看多")

    def test_low_confidence_lesson(self):
        r = evo_memory.analyze_reflect(
            {"kind": "技术", "ticker": "000001", "verdict": "观望",
             "confidence": 0.2, "model_engine": "deepseek"})
        self.assertIn("置信度仅", r["lesson"])

    def test_persisted_and_aggregated(self):
        evo_memory.analyze_reflect(
            {"kind": "估值", "ticker": "AAPL", "verdict": "看多",
             "confidence": 0.8, "model_engine": "ling"})
        evo_memory.analyze_reflect(
            {"kind": "估值", "ticker": "MSFT", "verdict": "看空",
             "confidence": 0.75, "model_engine": "ling"})
        agg = evo_memory.analysis_lessons()
        self.assertEqual(agg["total"], 2)
        self.assertEqual(agg["by_kind"]["估值"]["count"], 2)
        self.assertEqual(agg["by_kind"]["估值"]["high_conf"], 2)
        self.assertEqual(len(agg["recent"]), 2)

    def test_confidence_clamped(self):
        r = evo_memory.analyze_reflect(
            {"kind": "宏观", "confidence": 9.9, "verdict": "看多"})
        self.assertLessEqual(r["confidence"], 1.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
