# -*- coding: utf-8 -*-
"""时间完整性审计（chronoaudit）单元测试。"""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("STOCKAI_MOCK", "1")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pandas as pd  # noqa: E402

from core.chronoaudit import (audit_bars, detect_bar_stamping, format_report,  # noqa: E402
                              gate)


def _clean(n: int = 60) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    return pd.DataFrame({"close": range(n)}, index=idx)


class TestCleanData(unittest.TestCase):
    def test_clean_business_day_passes(self):
        r = audit_bars(_clean(), "CN", "1d")
        self.assertTrue(r["passed"])
        self.assertEqual(r["counts"]["FATAL"], 0)
        self.assertEqual(r["findings"], [])

    def test_convention_detected(self):
        self.assertEqual(audit_bars(_clean())["convention"]["convention"], "date_only")

    def test_gate_admits_clean(self):
        g = gate(_clean())
        self.assertTrue(g["admitted"])
        self.assertEqual(g["reason"], "")


class TestFatalDefects(unittest.TestCase):
    def test_duplicate_timestamps(self):
        df = _clean(20)
        df = pd.concat([df, df.iloc[[5]]])
        r = audit_bars(df, "CN", "1d")
        self.assertFalse(r["passed"])
        self.assertTrue(any(f["rule_id"] == "C01" and f["severity"] == "FATAL"
                            for f in r["findings"]))

    def test_non_monotonic_index(self):
        df = _clean(20)
        df = df.iloc[[0, 1, 2, 1, 3, 4]]
        r = audit_bars(df, "CN", "1d")
        self.assertTrue(any(f["rule_id"] == "C02" for f in r["findings"]))

    def test_future_timestamps(self):
        idx = pd.date_range("2099-01-01", periods=10, freq="D")
        r = audit_bars(pd.DataFrame({"close": range(10)}, index=idx), "CN", "1d")
        self.assertTrue(any(f["rule_id"] == "C03" for f in r["findings"]))

    def test_empty_data(self):
        r = audit_bars(pd.DataFrame(), "CN", "1d")
        self.assertFalse(r["passed"])
        self.assertTrue(any(f["rule_id"] == "C00" for f in r["findings"]))

    def test_gate_blocks_dirty(self):
        df = _clean(20)
        df = pd.concat([df, df.iloc[[3]]])
        g = gate(df)
        self.assertFalse(g["admitted"])
        self.assertTrue(g["reason"])


class TestWarnDefects(unittest.TestCase):
    def test_weekend_bars_for_cn(self):
        idx = pd.date_range("2024-01-01", periods=14, freq="D")
        r = audit_bars(pd.DataFrame({"close": range(14)}, index=idx), "CN", "1d")
        self.assertTrue(any(f["rule_id"] == "C04" for f in r["findings"]))

    def test_close_stamping_warns_lookahead(self):
        idx = pd.date_range("2024-01-01", periods=20, freq="B").map(
            lambda t: t.replace(hour=15, minute=0))
        r = audit_bars(pd.DataFrame({"close": range(20)}, index=pd.DatetimeIndex(idx)),
                       "CN", "1d")
        self.assertTrue(any(f["rule_id"] == "C07" for f in r["findings"]))
        self.assertEqual(r["convention"]["convention"], "close")

    def test_gap_detection(self):
        idx = list(pd.date_range("2024-01-01", periods=10, freq="B"))
        idx += list(pd.date_range("2024-06-01", periods=10, freq="B"))  # 跳空 5 个月
        r = audit_bars(pd.DataFrame({"close": range(20)}, index=pd.DatetimeIndex(idx)),
                       "CN", "1d")
        self.assertTrue(any(f["rule_id"] == "C05" for f in r["findings"]))

    def test_dst_offset_drift(self):
        idx = pd.date_range("2024-03-01", periods=40, freq="D", tz="UTC")
        s = pd.Series(idx).dt.tz_convert("Europe/London")
        r = audit_bars(pd.DataFrame({"close": range(40)}, index=pd.DatetimeIndex(s)),
                       "US", "1d")
        self.assertTrue(any(f["rule_id"] == "C06" for f in r["findings"]),
                        "夏令时切换应被识别为时区偏移漂移")


class TestConventionDetection(unittest.TestCase):
    def test_open_stamping(self):
        idx = pd.DatetimeIndex([t.replace(hour=9, minute=30)
                                for t in pd.date_range("2024-01-01", periods=10, freq="B")])
        self.assertEqual(detect_bar_stamping(idx)["convention"], "open")

    def test_intraday(self):
        idx = pd.DatetimeIndex([t.replace(hour=11, minute=0)
                                for t in pd.date_range("2024-01-01", periods=10, freq="B")])
        self.assertEqual(detect_bar_stamping(idx)["convention"], "intraday")

    def test_empty(self):
        self.assertEqual(detect_bar_stamping(pd.DatetimeIndex([]))["convention"], "unknown")


class TestReport(unittest.TestCase):
    def test_format_clean(self):
        self.assertIn("未发现", format_report(audit_bars(_clean())))

    def test_format_dirty_has_block_marker(self):
        df = _clean(20)
        df = pd.concat([df, df.iloc[[2]]])
        txt = format_report(audit_bars(df))
        self.assertIn("⛔", txt)
        self.assertIn("修复", txt)
        self.assertIn("bar-stamping", txt)


if __name__ == "__main__":
    unittest.main(verbosity=2)
    print("ALL PASS")
