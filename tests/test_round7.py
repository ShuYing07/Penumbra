# -*- coding: utf-8 -*-
"""本轮（模块一~六）回归测试。

覆盖：AGI 路由、可验证推理链、符号回归、A股特色分析师、
人类审校门、15 策略问股、六渠道推送、多源 ETL、wickra 桥、
回测分级审计、事件驱动回测、CFA 分析、工作流运行器、
监管验证器（多管辖区）。
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd


def _bars(n=120, seed=4):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2025-01-01", periods=n)
    close = pd.Series(100 * np.cumprod(1 + rng.normal(0.001, 0.02, n)),
                      index=idx)
    return pd.DataFrame({"open": close, "high": close * 1.01,
                         "low": close * 0.99, "close": close,
                         "volume": rng.integers(1e5, 5e5, n)}, index=idx)


class TestRound7(unittest.TestCase):

    def test_agi_router(self):
        from core.agi_router import RouteDecision, normalize_task, route
        self.assertEqual(normalize_task("技术面分析"), "technical")
        self.assertEqual(normalize_task("帮我看看财报"), "fundamental")
        self.assertEqual(normalize_task("辩论一下"), "debate")
        self.assertEqual(normalize_task("随便聊聊"), "quick")
        for task in ("fundamental", "debate", "backtest", "rag", "report",
                     "quick", "multimodal", "technical", "未知任务"):
            d = route(task, {})
            self.assertIsInstance(d, RouteDecision)
            self.assertIsInstance(d.model, str)
        self.assertEqual(route("财报分析", {}).task, "fundamental")
        cfg = {"models": {"task_routing":
                          {"fundamental": {"platform": "ollama",
                                           "model": "qwen2.5:7b"}}}}
        d2 = route("财报", cfg)
        self.assertEqual(d2.platform, "ollama")
        self.assertEqual(d2.source, "config")

    def test_verifiable_chain(self):
        from core.verifiable_chain import (extract_verifiable_steps,
                                           validate_chain, chain_markdown)
        text = ("步骤1｜结论：RSI(14)=62.9 中性偏强｜数据来源：近30日收盘价"
                "（获取于2026-09-30）｜公式：RSI=100-100/(1+RS)\n"
                "步骤2｜结论：MACD 金叉｜数据来源：日线 close｜公式：MACD=DIF-DEA")
        steps = extract_verifiable_steps(text)
        self.assertEqual(len(steps), 2)
        self.assertEqual(validate_chain(steps)["verdict"], "PASS")
        self.assertEqual(validate_chain([])["verdict"], "EMPTY")
        self.assertIn("步骤1", chain_markdown(steps))

    def test_symbolic_fit(self):
        from core.quant.symbolic_fit import discover_valuation_equation
        snap = [{"revenue": 100 + i * 10, "margin": 0.2 + i * 0.01,
                 "growth": 0.05 + i * 0.005,
                 "value": (100 + i * 10) * (0.2 + i * 0.01) * 10}
                for i in range(10)]
        r = discover_valuation_equation(snap)
        formulas = [c["formula"] for c in r["candidates"]]
        self.assertIn(r["best_formula"], formulas)
        self.assertGreaterEqual(r["r2"], 0.0)
        empty = discover_valuation_equation([])
        self.assertIn("error", empty)
        self.assertIn("样本不足", empty["error"])

    def test_ashare_analysts(self):
        from core.agents.ashare_analysts import (policy_analyst,
                                                 run_ashare_group,
                                                 volume_price_analyst)
        st = {"data": {"bars": _bars(30, seed=3)},
              "news": [{"title": "央行宣布降准0.5个百分点"}]}
        out = policy_analyst(dict(st))
        self.assertEqual(out["signals"]["policy"]["stance"], "看多")
        vp = volume_price_analyst(dict(st))
        self.assertIn(vp["signals"]["volume_price"]["stance"],
                      ("看多", "看空", "中性"))
        state = run_ashare_group(dict(st))
        self.assertEqual(set(state["signals"].keys()),
                         {"policy", "hot_money", "unlock", "volume_price"})

    def test_human_review(self):
        import tempfile
        from core.human_review import ReviewGate
        with tempfile.TemporaryDirectory() as td:
            g = ReviewGate(db=os.path.join(td, "r.db"))
            rec = g.create("第一段结论。\n第二段结论。\n",
                           {"ticker": "600519"})
            self.assertFalse(g.can_commit(rec.review_id))   # 未审校禁止提交
            g.approve_segment(rec.review_id, rec.segments[0]["id"])
            g.reject_segment(rec.review_id, rec.segments[1]["id"])
            self.assertTrue(g.can_commit(rec.review_id))    # 部分通过可提交
            text = g.commit_payload(rec.review_id)
            self.assertIn("第一段结论", text)
            self.assertNotIn("第二段结论", text)
            r2 = g.create("只一段。", {})
            g.reject_segment(r2.review_id, r2.segments[0]["id"])
            self.assertFalse(g.can_commit(r2.review_id))    # 全部驳回禁提交

    def test_strategies(self):
        from core.strategies import list_strategies, run_strategy, ask_strategy
        self.assertEqual(len(list_strategies()), 15)
        r = run_strategy("ma_cross", _bars(120))
        self.assertIn("stance", r)
        a = ask_strategy("ma_cross", "现在能买吗？", _bars(120))
        self.assertTrue(a["answer"])

    def test_push_channels(self):
        from core.push.channels import build_wecom_payload, push
        pl = build_wecom_payload("测试简报", "标题")
        self.assertEqual(pl["msgtype"], "text")
        r = push("测试简报", "标题", {}, "wecom")
        self.assertIsInstance(r, list)
        self.assertFalse(r[0]["ok"])                        # 未配置降级

    def test_multi_source_etl(self):
        from core.etl.multi_source_etl import (join_filings_news,
                                               make_newsapi_adapter)
        filings = [{"title": "茅台发布年报", "date": "2025-01-10"}]
        news = [{"title": "茅台发布年报", "published": "2025-01-11T09:00:00"}]
        merged = join_filings_news(filings, news, window_days=7)
        self.assertEqual(len(merged), 1)
        self.assertEqual(int(merged["gap_days"].iloc[0]), 1)
        adapter = make_newsapi_adapter()
        self.assertEqual(adapter.run(), [])          # 网络受限降级空
        self.assertFalse(adapter.ok)

    def test_wickra_bridge(self):
        from core.features.wickra_bridge import (wickra_available,
                                                 compute_features)
        self.assertFalse(wickra_available())                # 未安装
        feats = compute_features(_bars(120))
        self.assertIn("rsi14", feats)
        self.assertEqual(compute_features(None), {})
        self.assertEqual(compute_features(_bars(20)), {})   # 样本不足

    def test_backtest_audit(self):
        from core.quant.backtest_audit import backtest_audit
        bars = _bars(200)
        r = backtest_audit(bars, "CN", "ma_cross", n_perm=60)
        self.assertIn(r["grade"], ("A", "B", "C", "D"))
        self.assertIsInstance(r["score"], (int, float))
        self.assertIn("items", r)

    def test_event_backtest(self):
        from core.quant.event_engine import run_event_backtest
        bars = _bars(250, seed=9)

        def sig(df, i):
            if i < 20:
                return 0
            return 100 if df["close"].iloc[-5:].mean() > \
                df["close"].iloc[-20:].mean() else 0

        r = run_event_backtest(bars, sig)
        self.assertGreater(r["stats"]["n_trades"], 0)
        self.assertEqual(r["fee_model"]["lot"], 100)
        self.assertTrue(r["fee_model"]["t1"])
        self.assertGreater(r["trades"][0].fee, 0)

    def test_cfa_analysis(self):
        from core.quant.cfa_analysis import (calculate_ratios, ddm_gordon,
                                             risk_metrics, cfa_report)
        self.assertAlmostEqual(ddm_gordon(1, 0.05, 0.10), 21.0)
        fin = {"revenue": 1000.0, "net_income": 120.0, "equity": 600.0,
               "total_assets": 1500.0, "total_liabilities": 900.0,
               "current_assets": 500.0, "current_liabilities": 300.0,
               "gross_profit": 400.0, "operating_cash_flow": 150.0,
               "revenue_prev": 850.0, "net_income_prev": 100.0}
        ratios = calculate_ratios(fin)
        self.assertAlmostEqual(ratios["net_margin"], 0.12)
        self.assertAlmostEqual(ratios["roe"], 0.20)
        ret = pd.Series(np.random.default_rng(6).normal(0.0005, 0.02, 200))
        rm = risk_metrics(ret)
        self.assertLessEqual(rm["max_drawdown"], 0)
        full = cfa_report(fin, ret, {"dps": 0.8, "growth": 0.05,
                                     "required_return": 0.10})
        self.assertIn("ddm", full["valuation"])

    def test_workflow_runner(self):
        from core.workflow.runner import (DEFAULT_FLOW, NODE_REGISTRY,
                                          run_workflow)
        self.assertEqual(len(DEFAULT_FLOW), 5)
        self.assertEqual(len(NODE_REGISTRY), 5)
        r = run_workflow(DEFAULT_FLOW, ticker="600519", bars=_bars(120))
        self.assertEqual(len(r["results"]), 5)
        self.assertTrue(r["ok"])
        self.assertIn("# 分析报告", r["report"])
        r2 = run_workflow(["fetch_data", "gen_report"], ticker="TEST.XX")
        self.assertTrue(r2["ok"])                          # degraded 不算 error

    def test_regulatory_validator(self):
        from security.regulatory_validator import (compliance_report,
                                                   rules_for,
                                                   validate_record)
        self.assertIn("structuring_split", rules_for(["CN"]))
        rec = {"content": "看好长期", "position_pct": 0.3, "transfers": [],
               "threshold": 10000, "day": "1", "unpublished": ["重组预案"]}
        res = validate_record(rec, ["CN"])
        self.assertTrue(any(not r["passed"] for r in res))
        rpt = compliance_report([rec, {"content": "正常", "position_pct": 0.1,
                                       "transfers": [], "threshold": 10000,
                                       "day": "1", "unpublished": []}], ["CN"])
        self.assertEqual(rpt["grade"], "B")


if __name__ == "__main__":
    unittest.main(verbosity=2)
