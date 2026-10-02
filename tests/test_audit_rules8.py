# -*- coding: utf-8 -*-
"""回测八条分级审计规则测试：确定性数据 → 8 条规则结构、分级、诚实/吹大对比。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("STOCKAI_MOCK", "1")

import numpy as np
import pandas as pd


def _make_df(n=300, seed=11, sine=True):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2024-01-01", periods=n)
    close = 100 * np.cumprod(1 + rng.normal(0.0003, 0.004, n))
    if sine:
        close = close + np.sin(np.linspace(0, 6 * np.pi, n)) * 15
    close = pd.Series(np.clip(close, 5, None), index=idx)
    return pd.DataFrame({"open": close, "high": close * 1.01,
                         "low": close * 0.99, "close": close,
                         "volume": rng.integers(1e5, 5e5, n).astype(float)},
                        index=idx)


class TestAuditRules8(unittest.TestCase):
    def test_structure_eight_rules(self):
        from core.quant.audit_rules8 import audit8, RULE_SEVERITY
        rep = audit8(_make_df(), "CN", "ma_cross", n_perm=40)
        self.assertEqual(len(rep["rules"]), 8)
        self.assertEqual({r["id"] for r in rep["rules"]}, set(RULE_SEVERITY))
        for k in ("grade", "score", "summary", "passed", "honest_vs_inflated"):
            self.assertIn(k, rep)
        self.assertIn(rep["grade"], ("A", "B", "C", "D"))
        self.assertTrue(0 <= rep["score"] <= 100)

    def test_time_alignment_catches_weekend(self):
        from core.quant.audit_rules8 import rule_time_alignment
        df = _make_df(120)
        # 把索引换成自然日（含周末）→ 必须 fail
        df2 = df.copy()
        df2.index = pd.date_range("2024-01-01", periods=len(df2))
        r = rule_time_alignment(df2, "CN")
        self.assertEqual(r["status"], "fail")
        self.assertIn("周末", r["detail"])
        # 正常工作日索引 → pass
        r_ok = rule_time_alignment(df, "CN")
        self.assertEqual(r_ok["status"], "pass")

    def test_time_alignment_catches_duplicates(self):
        from core.quant.audit_rules8 import rule_time_alignment
        df = _make_df(130)
        dup = pd.concat([df, df.iloc[[-1]]])
        r = rule_time_alignment(dup, "CN")
        self.assertEqual(r["status"], "fail")
        self.assertIn("重复", r["detail"])

    def test_multiple_testing_bonferroni(self):
        from core.quant.audit_rules8 import rule_multiple_testing
        r1 = rule_multiple_testing(1)
        self.assertEqual(r1["status"], "pass")
        # 试错 20 次 → 校正门槛 99.75%；观测 95% 未达 → warn
        r2 = rule_multiple_testing(20, observed_percentile=95.0)
        self.assertEqual(r2["status"], "warn")
        self.assertAlmostEqual(r2["evidence"]["required_percentile"], 99.75)
        # 观测 99.9% 超过门槛 → pass
        r3 = rule_multiple_testing(20, observed_percentile=99.9)
        self.assertEqual(r3["status"], "pass")

    def test_cost_neglect_zero_fee_comparison(self):
        from core.quant.audit_rules8 import rule_cost_neglect
        r = rule_cost_neglect(_make_df(), "CN", "ma_cross", None, None)
        self.assertIn(r["status"], ("pass", "warn", "fail"))
        ev = r["evidence"]
        self.assertIn("net_return", ev)
        self.assertIn("zero_fee_return", ev)
        # 零费收益 ≥ 诚实收益（成本只可能侵蚀收益）
        self.assertGreaterEqual(ev["zero_fee_return"], ev["net_return"] - 1e-6)

    def test_liquidity_participation(self):
        from core.quant.audit_rules8 import rule_liquidity
        r = rule_liquidity(_make_df(), "CN", "ma_cross", None, None)
        self.assertIn(r["status"], ("pass", "warn", "fail", "na"))
        self.assertIn("worst_participation", r["evidence"])
        # 无 volume 列 → na
        df_novol = _make_df(120).drop(columns=["volume"])
        r2 = rule_liquidity(df_novol, "CN", "ma_cross", None, None)
        self.assertEqual(r2["status"], "na")

    def test_honest_vs_inflated(self):
        from core.quant.audit_rules8 import honest_vs_inflated
        r = honest_vs_inflated(_make_df(), "CN", "ma_cross")
        for k in ("honest", "inflated", "gap", "verdict"):
            self.assertIn(k, r)
        h = r["honest"]
        self.assertIn("total_return_pct", h)
        # 吹大版本总收益不低于诚实版本
        self.assertGreaterEqual(r["inflated"]["total_return_pct"],
                                h["total_return_pct"] - 1e-6)

    def test_format_report(self):
        from core.quant.audit_rules8 import audit8, format_audit8
        text = format_audit8(audit8(_make_df(), "CN", "ma_cross", n_perm=40))
        self.assertIn("八条审计", text)
        self.assertIn("前视偏差", text)
        self.assertIn("时间对齐", text)
        self.assertIn("诚实 vs 吹大", text)

    def test_severity_grades(self):
        from core.quant.audit_rules8 import RULE_SEVERITY
        self.assertEqual(RULE_SEVERITY["lookahead"], "critical")
        self.assertEqual(RULE_SEVERITY["time_alignment"], "critical")
        self.assertEqual(RULE_SEVERITY["overfitting"], "high")
        self.assertEqual(RULE_SEVERITY["liquidity"], "high")
        self.assertEqual(RULE_SEVERITY["survivorship"], "info")
        self.assertEqual(len(RULE_SEVERITY), 8)


if __name__ == "__main__":
    unittest.main(verbosity=2)
