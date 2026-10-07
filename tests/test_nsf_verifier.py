# -*- coding: utf-8 -*-
"""VA-NSF 神经符号约束验证器测试：硬约束拦截 / 批准证书 / 数值溯源 / 流式护栏。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("STOCKAI_MOCK", "1")


BAD = "建议买入 SH600519，目标价 2000 元，稳赚不赔，可加杠杆满仓。"
GOOD = ("贵州茅台（SH600519）最新收盘价 1680.0 元，PE 28.0，RSI14 为 62.9；"
        "近 60 日涨跌幅 +5.2%。历史波动率 24.5%，最大回撤 -12.3% 提示风险。"
        "本文仅陈述客观数据，不构成投资建议，仅供研究参考。")
EVIDENCE = {"close": 1680.0, "pe": 28.0, "rsi14": 62.9,
            "chg60": 5.2, "vol": 24.5, "mdd": -12.3}


class TestHardConstraints(unittest.TestCase):
    def test_violating_text_blocked(self):
        from security.nsf_verifier import verify
        v = verify(BAD, {"evidence": {}})
        self.assertFalse(v.approved)
        ids = {x.id for x in v.violations}
        self.assertTrue({"H01", "H02", "H03", "B02"} <= ids, ids)
        self.assertLess(v.score, 60)
        self.assertEqual(v.certificate, {})   # 未通过不签发证书

    def test_compliant_text_approved(self):
        from security.nsf_verifier import verify
        v = verify(GOOD, {"evidence": EVIDENCE})
        self.assertTrue(v.approved, v.report())
        self.assertTrue(v.certificate)
        self.assertIn("fingerprint", v.certificate)
        self.assertGreaterEqual(v.score, 90)

    def test_each_hard_constraint_triggers(self):
        from security.nsf_verifier import verify, CONSTRAINTS
        cases = {
            "H01": "综合来看建议买入 SH600519。",
            "H02": "该股目标价 88 元。",
            "H03": "这只股稳赚不赔。",
            "H04": "有内幕消息称庄家将拉升。",
            "H05": "该股明年必将翻倍。",
        }
        for cid, text in cases.items():
            v = verify(text)
            ids = {x.id for x in v.violations}
            self.assertIn(cid, ids, f"{cid} 未触发：{text}")
        self.assertEqual(len(CONSTRAINTS), 12)

    def test_negation_context_not_false_positive(self):
        """否定语境（不建议买入）不该误判为荐股。"""
        from security.nsf_verifier import _c_no_recommendation
        self.assertTrue(_c_no_recommendation("不建议买入 SH600519，仅供参考。", {}))


class TestNumericGrounding(unittest.TestCase):
    def test_hallucinated_numbers_blocked(self):
        from security.nsf_verifier import verify
        hallu = ("该股收盘价 9999.0 元，PE 888.0，RSI14 为 5.0，"
                 "波动剧烈存在风险。本文不构成投资建议。")
        v = verify(hallu, {"evidence": EVIDENCE})
        self.assertFalse(v.approved)
        self.assertIn("N02", {x.id for x in v.violations})

    def test_no_evidence_skips_numeric_check(self):
        """未提供 evidence 时，数值检查跳过（不误伤纯叙述文本）。"""
        from security.nsf_verifier import verify
        v = verify("该股近期表现平稳。本文不构成投资建议，注意风险。")
        self.assertNotIn("N02", {x.id for x in v.violations})

    def test_unknown_metric_blocked(self):
        from security.nsf_verifier import verify
        v = verify("根据自研神秘指标：88，建议关注风险。本文不构成投资建议。")
        self.assertIn("N01", {x.id for x in v.violations})


class TestBusinessRules(unittest.TestCase):
    def test_position_cap(self):
        from security.nsf_verifier import verify
        v = verify("建议配置比例 45% 仓位。本文不构成投资建议，注意风险。",
                   {"max_position_pct": 20.0})
        self.assertIn("B01", {x.id for x in v.violations})
        v2 = verify("建议配置比例 15% 仓位。本文不构成投资建议，注意风险。",
                    {"max_position_pct": 20.0})
        self.assertNotIn("B01", {x.id for x in v2.violations})


class TestStreamGuardrail(unittest.TestCase):
    def test_stream_hits_critical_early(self):
        from security.nsf_verifier import guard_stream
        fired = []
        _text, hits = guard_stream(
            list(BAD), on_violation=lambda vs, b: fired.append(vs[0].id))
        self.assertTrue(fired)
        self.assertTrue({h.id for h in hits} & {"H01", "H02", "H03"})

    def test_clean_stream_no_hits(self):
        from security.nsf_verifier import guard_stream
        _t, hits = guard_stream(list(GOOD))
        self.assertEqual(hits, [])


class TestCustomConstraints(unittest.TestCase):
    def test_load_constraints_override(self):
        import json
        import tempfile
        from security.nsf_verifier import load_constraints
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            p = os.path.join(td, "c.json")
            with open(p, "w", encoding="utf-8") as f:
                json.dump([{"id": "S02", "severity": "low"}], f)
            cons = load_constraints(p)
            self.assertEqual(cons[0].severity == "low", True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
