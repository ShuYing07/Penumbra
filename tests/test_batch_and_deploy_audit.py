# -*- coding: utf-8 -*-
"""批量回测网格 + 组合感知聚合 + D0–D4 部署审计测试。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("STOCKAI_MOCK", "1")

import numpy as np
import pandas as pd


def _bars_map(n=700, seed=21):
    rng = np.random.default_rng(seed)
    out = {}
    for i, code in enumerate(("A", "B", "C")):
        idx = pd.bdate_range("2021-01-01", periods=n)
        close = pd.Series(
            100 * np.cumprod(1 + rng.normal(0.0004 + i * 0.0002, 0.016, n)),
            index=idx)
        out[code] = pd.DataFrame(
            {"open": close, "high": close * 1.01, "low": close * 0.99,
             "close": close,
             "volume": rng.integers(1e5, 5e5, n).astype(float)}, index=idx)
    return out


class TestGrid(unittest.TestCase):
    def test_run_grid_cells(self):
        from core.quant.batch_backtest import run_grid
        wins = [("2021-01-01", "2022-12-31"), ("2023-01-01", "2024-12-31")]
        g = run_grid(_bars_map(), ["ma_cross", "rsi_reversion"], wins,
                     market="CN", min_bars=120)
        self.assertGreater(g["count"], 0)
        for c in g["cells"]:
            self.assertIn(c["strategy"], ("ma_cross", "rsi_reversion"))
            self.assertIn("total_return_pct", c["metrics"])

    def test_short_data_goes_to_failures(self):
        from core.quant.batch_backtest import run_grid
        tiny = {"S": _bars_map(n=700)["A"].iloc[:50]}
        g = run_grid(tiny, ["ma_cross"], min_bars=120)
        self.assertEqual(g["count"], 0)
        self.assertTrue(g["failures"])

    def test_single_failure_does_not_stop_batch(self):
        from core.quant.batch_backtest import run_grid
        bm = _bars_map()
        bm["BAD"] = None            # 故意掺入坏数据
        g = run_grid(bm, ["ma_cross"], market="CN", min_bars=120)
        self.assertGreater(g["count"], 0)          # 其余标的照常跑完
        self.assertTrue(any(f["code"] == "BAD" for f in g["failures"]))

    def test_grid_summary_dimensions(self):
        from core.quant.batch_backtest import run_grid, grid_summary
        g = run_grid(_bars_map(), ["ma_cross"], market="CN", min_bars=120)
        s = grid_summary(g)
        self.assertEqual(s["count"], g["count"])
        for dim in ("by_strategy", "by_code", "by_window"):
            self.assertTrue(s[dim], dim)
            for v in s[dim].values():
                self.assertGreaterEqual(v["win_rate_pct"], 0)
                self.assertLessEqual(v["win_rate_pct"], 100)


class TestPortfolioAggregate(unittest.TestCase):
    def test_weights_normalized_and_metrics_recomputed(self):
        from core.quant.batch_backtest import portfolio_aggregate
        idx = pd.bdate_range("2023-01-01", periods=200)
        rng = np.random.default_rng(5)
        eqs = {f"S{i}": pd.Series(
            100 * np.cumprod(1 + rng.normal(0.0005, 0.01, 200)), index=idx)
            for i in range(3)}
        agg = portfolio_aggregate(eqs, weights={"S0": 3, "S1": 1, "S2": 1})
        self.assertAlmostEqual(sum(agg["weights"].values()), 1.0, places=6)
        m = agg["metrics"]
        self.assertIn("max_drawdown_pct", m)
        self.assertIn("sharpe", m)
        # 组合回撤不差于最差成分（分散化）
        worst = min(float((s / s.cummax() - 1).min()) for s in eqs.values())
        self.assertGreaterEqual(m["max_drawdown_pct"] / 100.0, worst - 1e-6)

    def test_empty_input(self):
        from core.quant.batch_backtest import portfolio_aggregate
        self.assertEqual(portfolio_aggregate({})["n"], 0)


class TestDeployAudit(unittest.TestCase):
    CLEAN = '''
def signal(df, params):
    fast = df["close"].rolling(5).mean()
    slow = df["close"].rolling(20).mean()
    return (fast > slow).astype(int)
'''
    DIRTY = '''
def signal(df, params):
    future_close = df["close"].shift(-3)
    return (df["close"] > future_close).astype(int)

def save(path, text):
    with open(path, "w") as f:
        f.write(text)
'''

    def test_clean_passes(self):
        from core.quant.deploy_audit import deploy_audit
        r = deploy_audit(self.CLEAN, metrics={"total_return_pct": 5.0},
                         equity=pd.Series([1.0, 1.1, 1.2]))
        self.assertTrue(r["passed"])
        self.assertTrue(r["fingerprint"])
        self.assertEqual(r["grade"], "A")

    def test_dirty_hits_d0_d1_d2_d3(self):
        from core.quant.deploy_audit import deploy_audit
        idx = pd.date_range("2024-01-06", periods=10)   # 含周末
        bars = pd.DataFrame({"close": np.arange(10.0)}, index=idx)
        r = deploy_audit(self.DIRTY, metrics={"total_return_pct": float("nan")},
                         equity=pd.Series([1.0, np.nan, 1.2]),
                         bars=bars, market="CN")
        st = {c["id"]: c["status"] for c in r["checks"]}
        self.assertEqual(st["D0"], "fail")
        self.assertEqual(st["D1"], "fail")
        self.assertEqual(st["D2"], "fail")
        self.assertEqual(st["D3"], "warn")
        self.assertFalse(r["passed"])

    def test_fingerprint_detects_post_audit_edit(self):
        from core.quant.deploy_audit import deploy_audit, verify_unchanged
        r = deploy_audit(self.CLEAN)
        self.assertTrue(verify_unchanged(r, self.CLEAN)["unchanged"])
        v = verify_unchanged(r, self.CLEAN + "\n# 偷偷改了参数\n")
        self.assertFalse(v["unchanged"])
        self.assertIn("审完又改", v["message"])

    def test_five_checks_present(self):
        from core.quant.deploy_audit import deploy_audit
        r = deploy_audit(self.CLEAN)
        self.assertEqual([c["id"] for c in r["checks"]],
                         ["D0", "D1", "D2", "D3", "D4"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
