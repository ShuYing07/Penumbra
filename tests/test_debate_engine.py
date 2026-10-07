# -*- coding: utf-8 -*-
"""模块二 · Claim-level 结构化多空辩论引擎 单元测试。

重点验证三条硬约束：
1. 每个论点必须带证据（无证据不立论）；
2. 反驳必须结构化（有方法分类、有力度、判定是否有效）；
3. 全流程离线可跑、结果可复现（同样输入 → 同样计分）。

运行：venv\Scripts\python.exe -B tests\test_debate_engine.py
"""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("STOCKAI_MOCK", "1")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.agents.debate_engine import (  # noqa: E402
    Claim, Evidence, build_claims, rebut, run_claim_debate, tag_of, to_ui)


def _state() -> dict:
    return {
        "ticker": "SH600519",
        "signals": {
            "technical": {"stance": "看多", "confidence": 72,
                          "view": "均线多头排列，MACD 金叉",
                          "key_points": ["5日均线上穿60日均线", "MACD 金叉且量能放大"],
                          "risks": ["短线超买，RSI 达 74"]},
            "fundamental": {"stance": "中性", "confidence": 60,
                            "view": "估值处于近五年中位数附近",
                            "key_points": ["市盈率 21 倍", "ROE 连续三年 28%"],
                            "risks": ["营收增速放缓至 8%"]},
            "news": {"stance": "看空", "confidence": 65,
                     "view": "近期有减持公告",
                     "key_points": ["控股股东减持 1.2%", "行业政策收紧预期"],
                     "risks": ["负面舆情占比上升"]},
            "sentiment": {"stance": "中性", "confidence": 45,
                          "view": "讨论热度一般", "key_points": ["散户情绪偏观望"],
                          "risks": []},
        },
    }


class TestClaimBuilding(unittest.TestCase):
    def test_bull_claims_come_from_bullish_analysts(self):
        claims = build_claims(_state(), "bull", max_claims=3)
        self.assertTrue(claims, "看多分析师存在，应产出多方论点")
        self.assertTrue(all(c.side == "bull" for c in claims))
        self.assertLessEqual(len(claims), 3)

    def test_every_claim_has_evidence(self):
        """无证据不立论：任何返回出来的论点都必须带 Evidence。"""
        for side in ("bull", "bear"):
            for c in build_claims(_state(), side, max_claims=3):
                self.assertTrue(c.evidence, f"{side} 论点缺少证据：{c.text}")
                self.assertTrue(c.evidence[0].source)

    def test_bear_claims_include_cross_disclosed_risks(self):
        """看多分析师自我披露的风险，应被空方用作交叉质询素材。"""
        claims = build_claims(_state(), "bear", max_claims=5)
        texts = " ".join(c.text for c in claims)
        self.assertIn("短线超买", texts)      # 来自 technical（看多）的 risks
        self.assertIn("控股股东减持", texts)   # 来自 news（看空）的 key_points

    def test_claims_sorted_by_confidence_desc(self):
        claims = build_claims(_state(), "bear", max_claims=5)
        confs = [c.confidence for c in claims]
        self.assertEqual(confs, sorted(confs, reverse=True))

    def test_empty_signals_yield_no_claims(self):
        self.assertEqual(build_claims({"signals": {}}, "bull"), [])
        self.assertEqual(build_claims({}, "bear"), [])

    def test_topic_tagging(self):
        self.assertIn("技术", tag_of("MACD 金叉"))
        self.assertIn("估值", tag_of("市盈率偏高"))
        self.assertIn("风险", tag_of("存在减持风险"))
        self.assertEqual(tag_of("毫无信息量的一句话"), ["综合"])


class TestRebuttal(unittest.TestCase):
    def setUp(self):
        self.state = _state()

    def test_data_rebuttal_when_opposite_evidence_exists(self):
        claim = Claim(id="c1", side="bull", text="5日均线上穿60日均线",
                      evidence=[Evidence(source="technical", detail="均线多头")],
                      confidence=72, topics=["技术"])
        # 构造一个看空的技术面信号，应触发 data 型反驳
        self.state["signals"]["technical"]["stance"] = "看空"
        r = rebut(claim, self.state, "bear")
        self.assertEqual(r.method, "data")
        self.assertTrue(r.evidence)
        self.assertGreaterEqual(r.strength, 0.5)

    def test_magnitude_rebuttal_for_low_confidence(self):
        claim = Claim(id="c2", side="bull", text="未来可能上涨",
                      evidence=[Evidence(source="sentiment", detail="情绪回暖")],
                      confidence=30, topics=["综合"])
        r = rebut(claim, self.state, "bear")
        self.assertEqual(r.method, "magnitude")
        self.assertTrue(r.effective)

    def test_scope_rebuttal_when_no_numbers(self):
        claim = Claim(id="c3", side="bull", text="基本面持续向好",
                      evidence=[Evidence(source="fundamental", detail="盈利改善")],
                      confidence=80, topics=["业绩"])
        r = rebut(claim, self.state, "bear")
        self.assertEqual(r.method, "scope")
        self.assertIn("量化", r.text)

    def test_logic_rebuttal_is_not_effective(self):
        claim = Claim(id="c4", side="bull", text="营收同比增长 15%",
                      evidence=[Evidence(source="fundamental", detail="营收 +15%")],
                      confidence=80, topics=["业绩"])
        self.state["signals"]["fundamental"]["stance"] = "中性"
        r = rebut(claim, self.state, "bear")
        if r.method == "logic":
            self.assertFalse(r.effective)


class TestDebateFlow(unittest.TestCase):
    def test_two_rounds_structure(self):
        t = run_claim_debate(_state(), rounds=2)
        self.assertEqual(t.mode, "rule")
        self.assertGreaterEqual(len(t.rounds), 1)
        self.assertTrue(t.rounds[0].claims)
        # 每条第 1 轮论点都有对应反驳
        ids = {c.id for c in t.rounds[0].claims}
        rids = {r.claim_id for r in t.rounds[0].rebuttals}
        self.assertTrue(ids <= rids)

    def test_scores_are_normalized(self):
        t = run_claim_debate(_state(), rounds=2)
        if t.rounds and any(r.claims for r in t.rounds):
            self.assertAlmostEqual(t.bull_score + t.bear_score, 1.0, places=2)

    def test_deterministic_reproducible(self):
        a = run_claim_debate(_state(), rounds=2)
        b = run_claim_debate(_state(), rounds=2)
        self.assertEqual(a.bull_score, b.bull_score)
        self.assertEqual(a.bear_score, b.bear_score)
        self.assertEqual(len(a.rounds), len(b.rounds))

    def test_empty_state_degrades_gracefully(self):
        t = run_claim_debate({"ticker": "X", "signals": {}}, rounds=2)
        self.assertIn("不足", t.consensus)
        self.assertTrue(t.caveats)
        self.assertEqual(t.bull_score, t.bear_score)

    def test_winner_label(self):
        t = run_claim_debate(_state(), rounds=2)
        self.assertIn(t.winner, ("多方占优", "空方占优", "多空均衡"))

    def test_ui_shape_serializable(self):
        import json
        ui = to_ui(run_claim_debate(_state(), rounds=2))
        json.dumps(ui, ensure_ascii=False)      # 必须可序列化
        self.assertIn("rounds", ui)
        self.assertIn("winner", ui)
        for r in ui["rounds"]:
            for c in r["claims"]:
                self.assertTrue(c["evidence"])

    def test_rounds_capped_at_three(self):
        t = run_claim_debate(_state(), rounds=99)
        self.assertLessEqual(len(t.rounds), 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
    print("ALL PASS")
