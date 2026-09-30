# -*- coding: utf-8 -*-
"""本轮（模块一~七）回归测试。

覆盖：金融AI评测基准（八维/套件）、实时数据管道（滚动聚合/落库/源链）、
回测审计器（8 条分级规则/诚实vs偏差/CI 门）、事件演化图谱（三层/传导链/
因果推理）、AI评审员（目标价维度）、合规沙箱（31 场景）、高级绘图计算、
tick 回放、多图表同步总线、ReMe 自我进化记忆。
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd


def _bars(n=160, seed=7):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2025-01-01", periods=n)
    close = pd.Series(100 * np.cumprod(1 + rng.normal(0.001, 0.02, n)),
                      index=idx)
    return pd.DataFrame({"open": close, "high": close * 1.01,
                         "low": close * 0.99, "close": close,
                         "volume": rng.integers(1e5, 5e5, n)}, index=idx)


class TestRound8(unittest.TestCase):

    # ---------- 模块一：金融AI评测基准 ----------
    def test_eval_benchmark_8dim(self):
        from core.eval.eval_benchmark import evaluate_analysis, _DIMENSIONS
        ref = {"close": 320.5, "rsi14": 62.9, "pe": 28.0}
        good = ("### 摘要\n结论：RSI(14)=62.9 中性偏强。\n"
                "数据来源：AKShare日线（获取于 2026-09-28）。\n"
                "风险：PE 28 偏高，支撑 310。")
        r = evaluate_analysis(good, "分析茅台技术面", ref)
        self.assertEqual(set(r["scores"].keys()), set(_DIMENSIONS))
        self.assertGreater(r["total"], 0.6)
        bad = evaluate_analysis("这个股票应该能买点", "分析茅台技术面", ref)
        self.assertGreater(r["total"], bad["total"])

    def test_eval_suite_cases(self):
        from core.eval.eval_suite import STANDARD_CASES, run_case
        self.assertGreaterEqual(len(STANDARD_CASES), 4)
        text = ("### 回测解读\n总收益 12%，最大回撤 -8%。\n"
                "数据来源：回测日志（2025-01 至 2026-09）。结论：样本外有效。")
        res = run_case(text, STANDARD_CASES[3])
        self.assertIn("pass", res)
        self.assertIn("scores", res)

    # ---------- 模块二：实时数据管道 ----------
    def test_stream_pipeline_aggregate(self):
        from core.etl.stream_pipeline import window_aggregate, persist_ticks, \
            source_chain
        import time
        rows = [{"symbol": "600519", "price": 100 + i,
                 "change_pct": 0.01 * i, "volume": 1000.0,
                 "ts": time.time() - (8 - i) * 0.4, "source": "t"} for i in range(9)]
        agg = window_aggregate(rows, window_s=5)
        self.assertFalse(agg.empty)
        self.assertIn("symbol", agg.columns)
        self.assertIn("last_price", agg.columns)
        self.assertTrue(persist_ticks(rows) > 0)
        chain = source_chain("", "")
        self.assertEqual([s.priority for s in chain], [1, 2, 3])

    def test_stream_pipeline_empty(self):
        from core.etl.stream_pipeline import window_aggregate
        self.assertTrue(window_aggregate([], 5).empty)

    # ---------- 模块三：回测审计器 ----------
    def test_backtest_auditor_8rules(self):
        from core.quant.backtest_auditor import audit_strategy, \
            honest_vs_biased, audit_ci
        bars = _bars()
        r = audit_strategy(bars, "CN", "ma_cross", {"fast": 5, "slow": 20})
        self.assertEqual(len(r["checks"]), 8)
        self.assertIn(r["grade"], ("A", "B", "C", "D"))
        self.assertGreaterEqual(r["score"], 0)
        hb = honest_vs_biased(bars, "CN", "ma_cross", {"fast": 5, "slow": 20})
        self.assertIn("cost", hb)
        self.assertIn("lookahead", hb)
        ci = audit_ci(bars, "CN", "ma_cross", {"fast": 5, "slow": 20})
        self.assertIn("block", ci)
        self.assertIsInstance(ci["blocked_rules"], list)

    def test_backtest_auditor_time_align(self):
        from core.quant.backtest_auditor import _check_time_alignment
        bars = _bars(n=30)
        bad_idx = pd.date_range("2026-01-01", periods=20).append(
            pd.date_range("2025-01-01", periods=10))
        bad = bars.iloc[:30].copy()
        bad.index = bad_idx
        r = _check_time_alignment(bad)
        self.assertEqual(r["severity"], "critical")

    # ---------- 模块四：事件演化知识图谱 ----------
    def test_event_graph(self):
        from core.event_graph import build_from_texts, query_event_chain, \
            predict_impact
        texts = ["贵州茅台业绩预增，净利润同比增长15%",
                 "某股东减持套现1亿元", "公司收到政府补贴3000万元"]
        b = build_from_texts("600519", texts, industry="白酒")
        self.assertTrue(b["events"])
        chain = query_event_chain("600519", depth=3)
        self.assertTrue(chain["nodes"])
        self.assertTrue(chain["path"])
        imp = predict_impact("600519", texts, "白酒")
        self.assertTrue(imp["risk_scores"])
        self.assertTrue(imp["summary"])

    # ---------- 模块五：AI评审员（目标价维度）+ 合规沙箱 ----------
    def test_ai_reviewer_target_price(self):
        from security.ai_reviewer import review_output
        t = "目标价看到 500 元，维持买入评级"
        r = review_output(t)
        self.assertFalse(r["passed"])
        labels = {i["rule"] for i in r["issues"]}
        self.assertIn("target_price", labels)

    def test_compliance_sandbox_scenarios(self):
        from security.compliance_sandbox import SCENARIOS
        self.assertGreaterEqual(len(SCENARIOS), 31)

    # ---------- 模块六：高级绘图 / 回放 / 同步 ----------
    def test_drawings_advanced(self):
        from core.drawings_advanced import gann_angles, pitchfork, \
            harmonic_abcd, elliott_projection
        g = gann_angles({"x": 100.0, "y": 320.0})
        self.assertEqual(len(g), 3)
        self.assertAlmostEqual(g[0]["slope"], 1.0, places=5)
        pf = pitchfork({"x": 0.0, "y": 100.0}, {"x": 30.0, "y": 110.0},
                       {"x": 60.0, "y": 90.0})
        self.assertEqual(len(pf["median"]), 2)
        h = harmonic_abcd({"x": 0.0, "y": 100.0}, {"x": 10.0, "y": 110.0},
                          {"x": 20.0, "y": 105.0})
        self.assertTrue(h["valid"])
        self.assertEqual(len(h["variants"]), 4)
        e = elliott_projection([{"x": 0.0, "y": 100.0}, {"x": 10.0, "y": 120.0},
                                {"x": 20.0, "y": 110.0}, {"x": 30.0, "y": 130.0}])
        self.assertIsNotNone(e["target"])

    def test_playback(self):
        from core.quant.playback import PlaybackEngine, synthesize_ticks
        bars = _bars(n=20)
        tks = synthesize_ticks(bars, ticks_per_bar=8)
        self.assertEqual(len(tks), 160)
        self.assertEqual(tks[0]["i"], 0)
        self.assertEqual(tks[-1]["i"], 19)
        eng = PlaybackEngine(bars, ticks_per_bar=8)
        seen = []
        eng.on_step(lambda t: seen.append(t["price"]))
        eng.step(1)
        self.assertEqual(eng.position, 1)
        self.assertTrue(seen)
        eng.jump(50)
        self.assertEqual(eng.position, 50)
        self.assertGreaterEqual(eng.progress, 0)
        eng.set_speed(4.0)
        self.assertEqual(eng.speed, 4.0)
        self.assertEqual(PlaybackEngine(None).total, 0)

    def test_chart_sync_bus(self):
        from core.chart_sync import SyncBus, TOPIC_CURSOR
        bus = SyncBus()
        got = []
        bus.subscribe(TOPIC_CURSOR, lambda p: got.append(p))
        n = bus.publish(TOPIC_CURSOR, {"i": 1})
        self.assertEqual(n, 1)
        self.assertEqual(got, [{"i": 1}])
        self.assertEqual(bus.last(TOPIC_CURSOR), {"i": 1})

    # ---------- 模块七：ReMe 自我进化记忆 ----------
    def test_evo_memory(self):
        from core.agents.evo_memory import record_and_reflect, lessons, \
            style_profile, equity_curve, recent_reflections
        w = record_and_reflect({"code": "600519", "side": "多", "entry": 300.0,
                                "exit": 320.0, "qty": 100, "pnl": 2000.0,
                                "hold_days": 12, "reason": "均线金叉趋势跟随"})
        self.assertEqual(w["reflection"]["outcome"], "win")
        l = record_and_reflect({"code": "600519", "side": "多", "entry": 325.0,
                                "exit": 315.0, "qty": 100, "pnl": -1000.0,
                                "hold_days": 5, "reason": "超卖抄底未止损"})
        self.assertEqual(l["reflection"]["outcome"], "loss")
        ls = lessons()
        self.assertGreaterEqual(ls["total"], 2)
        self.assertAlmostEqual(ls["win_rate"],
                               ls["wins"] / ls["total"] if ls["total"] else 0)
        sp = style_profile()
        self.assertTrue(sp["profile"])
        self.assertEqual(sp["stats"]["trades"], ls["total"])
        eq = equity_curve()
        self.assertEqual(len(eq), ls["total"])
        self.assertEqual(eq[-1], round(1 + sp["stats"]["net_pnl"], 4))
        self.assertGreaterEqual(len(recent_reflections()), 2)


if __name__ == "__main__":
    unittest.main(verbosity=1)
