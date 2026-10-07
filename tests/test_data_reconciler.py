# -*- coding: utf-8 -*-
"""多源行情交叉核对（data_reconciler）单元测试。

reconcile() 是纯函数，无需网络即可完整验证对账逻辑。
"""
import os
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("STOCKAI_MOCK", "1")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.data_reconciler import (  # noqa: E402
    SourceQuote, best_quote, fetch_realtime_multi, format_report, reconcile,
    reconcile_realtime, score_source)

NOW = time.time()


class TestReconcile(unittest.TestCase):
    def test_consistent_sources(self):
        r = reconcile([SourceQuote("a", price=100.0, volume=100, ts=NOW),
                       SourceQuote("b", price=100.2, volume=100, ts=NOW)])
        self.assertEqual(r["severity"], "OK")
        self.assertTrue(r["ok"])
        self.assertAlmostEqual(r["consensus"], 100.1)
        self.assertIn(r["chosen"], ("a", "b"))

    def test_outlier_detected_and_penalized(self):
        r = reconcile([SourceQuote("good1", price=100.0, ts=NOW),
                       SourceQuote("good2", price=100.1, ts=NOW),
                       SourceQuote("bad", price=130.0, ts=NOW)])
        self.assertEqual(r["severity"], "WARN")
        bad = [d for d in r["deviations"] if d["source"] == "bad"][0]
        self.assertTrue(bad["outlier"])
        self.assertLess(r["scores"]["bad"], r["scores"]["good1"])
        self.assertNotEqual(r["chosen"], "bad")

    def test_all_sources_failed(self):
        r = reconcile([SourceQuote("a", ok=False, error="timeout"),
                       SourceQuote("b", ok=False, error="401")])
        self.assertEqual(r["severity"], "FATAL")
        self.assertFalse(r["ok"])
        self.assertEqual(r["chosen"], None)

    def test_partial_failure_warns_but_works(self):
        r = reconcile([SourceQuote("a", price=10.0, ts=NOW),
                       SourceQuote("b", ok=False, error="超时")])
        self.assertTrue(r["ok"])
        self.assertEqual(r["usable"], 1)
        self.assertTrue(any("b" in w for w in r["warnings"]))

    def test_single_source_cannot_cross_validate(self):
        r = reconcile([SourceQuote("a", price=10.0, ts=NOW),
                       SourceQuote("b", ok=False, error="x")])
        self.assertIn("无法交叉验证", " ".join(r["warnings"]))

    def test_timestamp_spread_warning(self):
        r = reconcile([SourceQuote("a", price=10.0, ts=NOW),
                       SourceQuote("b", price=10.0, ts=NOW - 3600)])
        self.assertTrue(any("时间戳" in w for w in r["warnings"]))
        self.assertGreater(r["ts_spread_s"], 3000)

    def test_empty_input(self):
        r = reconcile([])
        self.assertEqual(r["severity"], "FATAL")

    def test_no_price_field_is_unusable(self):
        r = reconcile([SourceQuote("a", price=None), SourceQuote("b", price=5.0)])
        self.assertEqual(r["usable"], 1)


class TestScoring(unittest.TestCase):
    def test_failed_source_scores_zero(self):
        self.assertEqual(score_source(SourceQuote("a", ok=False), 10.0, NOW, 1.0), 0.0)

    def test_fresh_and_complete_beats_stale(self):
        fresh = SourceQuote("f", price=10.0, volume=100, ts=NOW)
        stale = SourceQuote("s", price=10.0, ts=NOW - 7200)
        self.assertGreater(score_source(fresh, 10.0, NOW, 1.0),
                           score_source(stale, 10.0, NOW, 1.0))

    def test_score_bounded(self):
        s = score_source(SourceQuote("x", price=1e9, volume=1, ts=NOW), 10.0, NOW, 1.0)
        self.assertGreaterEqual(s, 0.0)
        self.assertLessEqual(s, 100.0)


class TestHelpers(unittest.TestCase):
    def test_best_quote(self):
        r = reconcile([SourceQuote("a", price=10.0, ts=NOW)])
        self.assertEqual(best_quote(r)["source"], "a")

    def test_format_report_fatal(self):
        r = reconcile([SourceQuote("a", ok=False, error="boom")])
        self.assertIn("⛔", format_report(r))

    def test_format_report_normal(self):
        r = reconcile([SourceQuote("a", price=10.0, ts=NOW),
                       SourceQuote("b", price=10.1, ts=NOW)])
        txt = format_report(r)
        self.assertIn("推荐源", txt)
        self.assertIn("共识价", txt)

    def test_fetch_unknown_source_degrades(self):
        qs = fetch_realtime_multi("SH600519", sources=["不存在的源"])
        self.assertEqual(len(qs), 1)
        self.assertFalse(qs[0].ok)

    def test_reconcile_realtime_never_raises(self):
        """离线环境下所有源都会失败，但不得抛异常。"""
        r = reconcile_realtime("SH600519", sources=("akshare",))
        self.assertIn("severity", r)
        self.assertEqual(r["ticker"], "SH600519")


if __name__ == "__main__":
    unittest.main(verbosity=2)
    print("ALL PASS")
