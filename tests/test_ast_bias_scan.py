# -*- coding: utf-8 -*-
"""模块三 · 回测代码 AST 静态审计 单元测试。

验证两件事：
1. 真阳性：LLM/新手最常写的 6 类前视偏差写法必须被抓到并判致命；
2. 零误报：正确写法（滚动窗口、信号滞后一 bar）不得被误伤——
   误报比漏报更致命，会让人养成无视告警的习惯。

运行：venv\Scripts\python.exe -B tests\test_ast_bias_scan.py
"""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("STOCKAI_MOCK", "1")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.quant.ast_bias_scan import (  # noqa: E402
    ScanReport, format_report, preflight, scan_file, scan_function, scan_source)


DIRTY = '''
import pandas as pd

def bad_strategy(df):
    df["fwd_ret"] = df["close"].shift(-1)
    df["fill"] = df["close"].bfill()
    df["mid"] = df["close"].rolling(20, center=True).mean()
    df["z"] = (df["close"] - df["close"].mean()) / df["close"].std()
    df["pct"] = df["close"].pct_change(-1)
    return df
'''

CLEAN = '''
import pandas as pd

def good_strategy(df):
    df["ma20"] = df["close"].rolling(20).mean()
    df["ma60"] = df["close"].rolling(60).mean()
    df["sig"] = (df["ma20"] > df["ma60"]).shift(1).fillna(False)
    return df
'''


class TestTruePositives(unittest.TestCase):
    def setUp(self):
        self.rep = scan_source(DIRTY, "dirty.py")

    def test_detects_all_rule_families(self):
        ids = {f.rule_id for f in self.rep.findings}
        self.assertIn("A01", ids)   # shift(-1) / pct_change(-1)
        self.assertIn("A02", ids)   # bfill
        self.assertIn("A03", ids)   # rolling(center=True)
        self.assertIn("A04", ids)   # 全样本归一化
        self.assertIn("A06", ids)   # 未来语义命名 fwd_ret

    def test_fatal_items_block_backtest(self):
        self.assertTrue(self.rep.blocking)
        self.assertFalse(self.rep.passed)
        fatals = self.rep.by_severity("FATAL")
        self.assertGreaterEqual(len(fatals), 3)

    def test_finding_has_five_tuple(self):
        """缺陷 × 证据 × 严重度 × 影响 × 修复，五要素齐全。"""
        for f in self.rep.findings:
            self.assertTrue(f.defect)
            self.assertTrue(f.evidence)
            self.assertIn(f.severity, ("FATAL", "WARN", "INFO"))
            self.assertTrue(f.impact)
            self.assertTrue(f.fix)

    def test_evidence_contains_file_and_line(self):
        f = self.rep.by_severity("FATAL")[0]
        self.assertIn("dirty.py", f.evidence)
        self.assertGreater(f.line, 0)

    def test_fillna_bfill_variant(self):
        src = 'def s(df):\n    return df["close"].fillna(method="bfill")\n'
        rep = scan_source(src, "x.py")
        self.assertTrue(any(f.rule_id == "A02" for f in rep.findings))

    def test_report_dict_shape(self):
        d = self.rep.to_dict()
        self.assertIn("counts", d)
        self.assertEqual(d["counts"]["FATAL"], len(self.rep.by_severity("FATAL")))
        self.assertTrue(d["blocking"])


class TestNoFalsePositives(unittest.TestCase):
    def test_clean_strategy_passes(self):
        rep = scan_source(CLEAN, "clean.py")
        self.assertEqual(rep.findings, [], f"误报：{[f.defect for f in rep.findings]}")
        self.assertTrue(rep.passed)

    def test_rolling_mean_not_flagged(self):
        src = 'def s(df):\n    return df["close"].rolling(20).mean()\n'
        self.assertEqual(scan_source(src, "r.py").findings, [])

    def test_groupby_mean_not_flagged(self):
        src = 'def s(df):\n    return df.groupby("code")["close"].mean()\n'
        self.assertEqual(scan_source(src, "g.py").findings, [])

    def test_positive_shift_not_flagged(self):
        src = 'def s(df):\n    return df["close"].shift(1)\n'
        self.assertEqual(scan_source(src, "p.py").findings, [])


class TestInputHandling(unittest.TestCase):
    def test_syntax_error_reported_not_raised(self):
        rep = scan_source("def broken(:\n", "bad.py")
        self.assertTrue(rep.error)
        self.assertIn("语法错误", rep.error)

    def test_empty_source(self):
        self.assertTrue(scan_source("", "e.py").error)

    def test_scan_function(self):
        def fn(df):
            return df["close"].shift(-2)
        rep = scan_function(fn)
        self.assertTrue(rep.blocking)
        self.assertTrue(any(f.rule_id == "A01" for f in rep.findings))

    def test_scan_file_missing(self):
        rep = scan_file("绝对不存在的路径.py")
        self.assertTrue(rep.error)

    def test_preflight_with_source(self):
        r = preflight(source='df["c"].shift(-1)')
        self.assertTrue(r["blocking"])

    def test_preflight_no_input(self):
        r = preflight()
        self.assertTrue(r["error"])

    def test_format_report_readable(self):
        txt = format_report(scan_source(DIRTY, "dirty.py"))
        self.assertIn("静态审计报告", txt)
        self.assertIn("修复", txt)
        self.assertIn("⛔", txt)

    def test_format_report_clean(self):
        txt = format_report(scan_source(CLEAN, "clean.py"))
        self.assertIn("通过", txt)

    def test_empty_report_object(self):
        r = ScanReport()
        self.assertTrue(r.passed)
        self.assertEqual(r.findings, [])


class TestIntegration(unittest.TestCase):
    """静态审计已接入回测审计报告的第一部分。"""

    def test_audit_strategy_includes_static_scan(self):
        import pandas as pd
        from core.quant.backtest_auditor import audit_strategy
        idx = pd.date_range("2024-01-01", periods=120, freq="D")
        df = pd.DataFrame({
            "open": range(100, 220), "high": range(101, 221),
            "low": range(99, 219), "close": range(100, 220),
            "volume": [1_000_000] * 120,
        }, index=idx)
        out = audit_strategy(df, "CN", "ma_cross")
        self.assertIn("static_scan", out)
        self.assertIn("target", out["static_scan"])
        # 内置策略应当通过静态审计（否则说明内置策略本身有前视偏差！）
        self.assertFalse(out["static_scan"].get("blocking", False),
                         f"内置策略命中致命项：{out['static_scan'].get('findings')}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
    print("ALL PASS")
