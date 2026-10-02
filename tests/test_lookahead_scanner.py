# -*- coding: utf-8 -*-
"""前视偏差扫描器测试：确定性数据 → 分级审计报告结构与逻辑。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("STOCKAI_MOCK", "1")

import numpy as np
import pandas as pd


def _make_df(n=300, seed=7):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2023-01-02", periods=n)
    close = 100 + np.cumsum(rng.normal(0, 1, n))
    close = np.clip(close, 20, None)
    open_ = close + rng.normal(0, 0.4, n)
    high = np.maximum(open_, close) + np.abs(rng.normal(0, 0.5, n))
    low = np.minimum(open_, close) - np.abs(rng.normal(0, 0.5, n))
    vol = rng.integers(100_000, 1_000_000, n).astype(float)
    return pd.DataFrame({"open": open_, "high": high, "low": low,
                         "close": close, "volume": vol, "chg_pct": 0.0},
                        index=dates)


class TestLookaheadScanner(unittest.TestCase):
    def test_scan_structure(self):
        from core.quant.lookahead_scanner import scan_strategy
        df = _make_df()
        r = scan_strategy(df, "rsi", {"period": 14}, market="CN")
        for k in ("passed", "severity", "suspicious_points", "mismatch_ratio",
                  "details", "honest_summary"):
            self.assertIn(k, r)
        self.assertIn("checklist", r["details"])
        self.assertEqual(len(r["details"]["checklist"]), 6)  # quant-backtest-guard 清单

    def test_na_strategy_not_flagged(self):
        from core.quant.lookahead_scanner import scan_strategy
        df = _make_df()
        r = scan_strategy(df, "buy_hold", {}, market="CN")
        self.assertTrue(r["passed"])  # 无信号函数 → na 视为通过

    def test_known_good_strategy_passes(self):
        from core.quant.lookahead_scanner import scan_strategy
        df = _make_df()
        r = scan_strategy(df, "ma_cross", {"fast": 5, "slow": 20}, market="CN")
        self.assertIn(r["severity"], ("通过", "提示"))

    def test_format_report(self):
        from core.quant.lookahead_scanner import scan_strategy, format_report
        df = _make_df()
        r = scan_strategy(df, "ma_cross", {"fast": 5, "slow": 20}, market="CN")
        text = format_report(r)
        self.assertIn("策略审计", text)
        self.assertIn("前视偏差扫描", text)
        self.assertIn("检查清单", text)

    def test_checklist_has_fatal_high_risk_rules(self):
        from core.quant.lookahead_scanner import CHECKLIST
        severities = {c["severity"] for c in CHECKLIST}
        self.assertIn("致命", severities)
        self.assertIn("高危", severities)
        rules = [c["rule"] for c in CHECKLIST]
        self.assertIn("未来函数/前视偏差", rules)
        self.assertIn("过拟合/数据窥探", rules)


if __name__ == "__main__":
    unittest.main(verbosity=2)
