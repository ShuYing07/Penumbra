# -*- coding: utf-8 -*-
"""TradeGrad 文本梯度策略优化测试：窗口划分 / 尾部CVaR / 迭代 / 留痕。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("STOCKAI_MOCK", "1")

import numpy as np
import pandas as pd


def _bars(n=900, seed=7):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2022-01-01", periods=n)
    seg = [rng.normal(0.0012, 0.012, 250), rng.normal(-0.0008, 0.020, 250),
           rng.normal(0.0006, 0.014, 250), rng.normal(0.0010, 0.010, 150)]
    close = pd.Series(100 * np.cumprod(1 + np.concatenate(seg)), index=idx)
    return pd.DataFrame({"open": close, "high": close * 1.01,
                         "low": close * 0.99, "close": close,
                         "volume": rng.integers(1e5, 5e5, n).astype(float)},
                        index=idx)


class TestScoring(unittest.TestCase):
    def test_window_returns_yearly(self):
        from core.quant.text_grad import window_returns
        s = pd.Series(np.random.default_rng(1).normal(0, 0.01, 600),
                      index=pd.bdate_range("2020-01-01", periods=600))
        w = window_returns(s)
        self.assertGreaterEqual(len(w), 2)
        self.assertTrue(all(isinstance(x, float) for x in w))

    def test_worst_cvar_tail_mean(self):
        from core.quant.text_grad import worst_cvar
        # 最差 30%：取 10 个中最差 4 个（ceil(10*0.3)=3 → 3 个）
        wins = [-0.5, -0.4, -0.1, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7]
        cv = worst_cvar(wins, 0.3)
        self.assertAlmostEqual(cv, (-0.5 - 0.4 - 0.1) / 3, places=6)
        # 全正 → CVaR 为正
        self.assertGreater(worst_cvar([0.1, 0.2, 0.3], 0.3), 0)
        self.assertEqual(worst_cvar([]), 0.0)

    def test_score_candidate_keys(self):
        from core.quant.text_grad import score_candidate
        s = score_candidate(_bars(), "CN", "ma_cross", {"fast": 5, "slow": 20})
        for k in ("score", "worst_cvar", "windows", "total_return"):
            self.assertIn(k, s)


class TestGradient(unittest.TestCase):
    def test_gradient_content(self):
        from core.quant.text_grad import text_gradient
        # 首轮无历史
        self.assertIn("首轮", text_gradient([], {}))
        # 尾部大亏 → 建议修复尾部
        g = text_gradient(
            [{"worst_cvar": -0.05, "params": {"fast": 5}}],
            {"worst_cvar": -0.30, "trade_count": 60, "windows": [-0.3, 0.1, 0.2]})
        self.assertIn("尾部", g)
        self.assertIn("换手", g)
        # 样本不足提示
        g2 = text_gradient([], {"worst_cvar": 0.1, "windows": [0.1, 0.2]})
        self.assertIn("未检出", g2)

    def test_neighbors_deterministic(self):
        from core.quant.text_grad import neighbors
        nb = neighbors({"fast": 5, "slow": 20})
        self.assertIn({"fast": 3, "slow": 20}, nb)
        self.assertIn({"fast": 8, "slow": 20}, nb)
        self.assertIn({"fast": 5, "slow": 30}, nb)
        self.assertEqual(neighbors({"unknown": 1}), [])


class TestIteration(unittest.TestCase):
    def test_iterate_improves_tail(self):
        from core.quant.text_grad import iterate
        res = iterate(_bars(), "CN", "ma_cross", {"fast": 5, "slow": 20},
                      n_iter=3)
        self.assertEqual(res["iterations"], 3)
        self.assertIn("best", res)
        self.assertIn("最差 30%", res["scoring"])
        # best 不劣于首轮
        self.assertGreaterEqual(res["best_score"],
                                res["history"][0]["worst_cvar"] - 1e-9)
        self.assertTrue(all(h.get("gradient") for h in res["history"]))

    def test_history_persisted(self):
        from core.quant.text_grad import iterate, iteration_history
        iterate(_bars(n=900, seed=3), "CN", "ma_cross",
                {"fast": 5, "slow": 20}, n_iter=2)
        hist = iteration_history("ma_cross", limit=5)
        self.assertGreaterEqual(len(hist), 1)
        self.assertIsInstance(hist[0]["params"], dict)
        self.assertIn("worst_cvar", hist[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
