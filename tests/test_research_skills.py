# -*- coding: utf-8 -*-
"""投研成果 Skill 化测试：输入校验 / 确定性执行 / 可解释输出 / 过程留痕。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("STOCKAI_MOCK", "1")

import numpy as np
import pandas as pd


def _make_bars(n=200, seed=5):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2025-01-01", periods=n)
    close = pd.Series(100 * np.cumprod(1 + rng.normal(0.0008, 0.02, n)), index=idx)
    open_ = close * (1 + rng.normal(0, 0.005, n))
    high = pd.Series(np.maximum(open_, close) * 1.008, index=idx)
    low = pd.Series(np.minimum(open_, close) * 0.992, index=idx)
    return pd.DataFrame({"open": open_, "high": high, "low": low,
                         "close": close,
                         "volume": rng.integers(1e5, 1e6, n).astype(float)},
                        index=idx)


def _pattern_bars():
    """手工构造含确定形态的 K 线：吞没 / 锤子 / 十字星。"""
    idx = pd.bdate_range("2025-06-01", periods=6)
    #            open  high   low  close
    rows = [  # 0: 阴线
        (10.0, 10.2, 9.5, 9.6),
        # 1: 看涨吞没（阳线完全吞没前阴）
        (9.5, 10.6, 9.4, 10.5),
        # 2: 十字星
        (10.5, 10.9, 10.1, 10.52),
        # 3: 锤子线（长下影）
        (10.4, 10.5, 9.0, 10.35),
        # 4-5: 普通
        (10.3, 10.4, 10.0, 10.1),
        (10.1, 10.2, 9.9, 10.0),
    ]
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"],
                        index=idx)


class TestSkillRegistry(unittest.TestCase):
    def test_registry_and_catalog(self):
        from core.research_skills import (RESEARCH_SKILLS,
                                          list_research_skills)
        self.assertEqual(set(RESEARCH_SKILLS),
                         {"factor_iteration", "kline_pattern_search",
                          "deep_research"})
        cat = list_research_skills()
        self.assertEqual(len(cat), 3)
        for item in cat:
            self.assertIn("description", item)
            self.assertIn("inputs", item)

    def test_unknown_skill_rejected(self):
        from core.research_skills import run_skill, SkillInputError
        with self.assertRaises(SkillInputError):
            run_skill("not_a_skill", {})


class TestFactorIteration(unittest.TestCase):
    def test_run_and_explain(self):
        from core.research_skills import run_skill
        r = run_skill("factor_iteration", {"bars": _make_bars()})
        self.assertIn("best", r)
        self.assertIn("ic", r["best"])
        self.assertTrue(r["research_only"])
        self.assertIn("样本内", r["explanation"])
        self.assertGreater(r["trace_id"], 0)
        self.assertGreater(len(r["candidates"]), 0)

    def test_missing_input_rejected(self):
        from core.research_skills import run_skill, SkillInputError
        with self.assertRaises(SkillInputError):
            run_skill("factor_iteration", {})
        with self.assertRaises(SkillInputError):
            run_skill("factor_iteration", {"bars": _make_bars(30)})


class TestKlinePatternSearch(unittest.TestCase):
    def test_known_patterns_detected(self):
        from core.research_skills import run_skill
        bars = _pattern_bars()
        r = run_skill("kline_pattern_search",
                      {"bars": bars, "min_strength": 0.3})
        found = {(m["pattern"], m["date"]) for m in r["matches"]}
        self.assertIn(("bullish_engulfing", str(bars.index[1])[:10]), found)
        self.assertIn(("doji", str(bars.index[2])[:10]), found)
        self.assertIn(("hammer", str(bars.index[3])[:10]), found)

    def test_pattern_filter_and_strength(self):
        from core.research_skills import run_skill
        bars = _pattern_bars()
        r = run_skill("kline_pattern_search",
                      {"bars": bars, "patterns": ["doji"], "min_strength": 0.8})
        self.assertTrue(all(m["pattern"] == "doji" for m in r["matches"]))
        self.assertTrue(all(m["strength"] >= 0.8 for m in r["matches"]))

    def test_unknown_pattern_rejected(self):
        from core.research_skills import run_skill, SkillInputError
        with self.assertRaises(SkillInputError):
            run_skill("kline_pattern_search",
                      {"bars": _pattern_bars(), "patterns": ["moon"]})

    def test_no_lookahead_in_detection(self):
        """形态判定只使用当日前数据：截断后同一位置的判定结果不变。"""
        from core.research_skills import PATTERN_LIBRARY
        bars = _pattern_bars()
        full = PATTERN_LIBRARY["bullish_engulfing"]["fn"](bars, 1)
        trunc = PATTERN_LIBRARY["bullish_engulfing"]["fn"](bars.iloc[:2], 1)
        self.assertEqual(full, trunc)
        self.assertGreater(full, 0)


class TestDeepResearch(unittest.TestCase):
    def test_full_skeleton(self):
        from core.research_skills import run_skill
        r = run_skill("deep_research", {
            "code": "SH600519", "bars": _make_bars(),
            "funda": {"name": "贵州茅台", "pe": 28.0, "pb": 9.5, "roe": 0.31}})
        sec = r["sections"]
        for k in ("概况", "财务", "估值", "技术", "风险", "结论"):
            self.assertIn(k, sec)
        self.assertIn("annual_volatility", sec["风险"])
        self.assertIn("不构成投资建议", r["explanation"])

    def test_minimal_input(self):
        from core.research_skills import run_skill
        r = run_skill("deep_research", {"code": "SH600519"})
        self.assertEqual(r["sections"]["结论"]["completed_sections"], [])
        self.assertIn("财务", r["sections"]["结论"]["missing"])

    def test_empty_code_rejected(self):
        from core.research_skills import run_skill, SkillInputError
        with self.assertRaises(SkillInputError):
            run_skill("deep_research", {"code": "  "})


class TestTraces(unittest.TestCase):
    def test_trace_recorded(self):
        from core.research_skills import run_skill, list_traces
        r = run_skill("deep_research", {"code": "TRACE001"})
        traces = list_traces(skill="deep_research", limit=5)
        self.assertGreaterEqual(len(traces), 1)
        self.assertEqual(traces[0]["skill"], "deep_research")
        self.assertEqual(traces[0]["id"], r["trace_id"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
