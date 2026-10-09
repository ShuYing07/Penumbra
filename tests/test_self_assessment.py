# -*- coding: utf-8 -*-
"""core/agents/self_assessment.py 结论级置信度自评单测。

验证：分档与配色、七因子权重归一化、无证据强制不足档、
分歧/未决争议/样本外衰减的降分与 caveat、辩论对接、展示层不产出违规内容。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("STOCKAI_MOCK", "1")

from core.agents import self_assessment as sa


# --------------------------------------------------------------------------
# 分档
# --------------------------------------------------------------------------
def test_bands_ordered_and_colored():
    assert [b["id"] for b in sa.BANDS] == ["high", "medium", "low", "insufficient"]
    for b in sa.BANDS:
        assert b["color"].startswith("#")
        assert b["action"] in ("show", "show_with_caveat", "needs_review", "block")
    # 置信度不得占用涨跌红绿
    assert "#00C853" not in {b["color"] for b in sa.BANDS}
    assert "#FF1744" not in {b["color"] for b in sa.BANDS}


def test_thresholds_monotonic():
    mins = [b["min"] for b in sa.BANDS]
    assert mins == sorted(mins, reverse=True)


# --------------------------------------------------------------------------
# 来源分层
# --------------------------------------------------------------------------
def test_tier_of_known_and_unknown():
    assert sa.tier_of("exchange") == 1.0
    assert sa.tier_of("filing") == 0.95
    assert sa.tier_of("social") == 0.30
    assert sa.tier_of("来自火星的传闻") == sa._DEFAULT_TIER


def test_tier_case_insensitive():
    assert sa.tier_of("EXCHANGE") == 1.0


# --------------------------------------------------------------------------
# 因子与权重
# --------------------------------------------------------------------------
def test_seven_factors_and_weights_sum_to_one():
    r = sa.assess(evidence=[{"source": "filing"}])
    assert len(r.factors) == 7
    assert abs(sum(f.weight for f in r.factors) - 1.0) < 1e-9


def test_contributions_sum_to_score():
    r = sa.assess(evidence=[{"source": "filing"}, {"source": "market"}],
                  freshness_days=2, disagreement=0.2, unresolved=0,
                  sample_size=200, oos_decay=0.1, self_report=80)
    assert abs(sum(f.contribution for f in r.factors) - r.score) < 0.15


def test_custom_weights_respected():
    r = sa.assess(evidence=[{"source": "filing"}],
                  weights={"evidence": 0.9, "freshness": 0.1})
    ev = next(f for f in r.factors if f.key == "evidence")
    assert ev.weight > 0.5


# --------------------------------------------------------------------------
# 硬约束：无证据
# --------------------------------------------------------------------------
def test_no_evidence_forces_insufficient():
    r = sa.assess(evidence=[], freshness_days=0, disagreement=0.0,
                  unresolved=0, sample_size=100000, oos_decay=0.0,
                  self_report=100)
    assert r.band == "insufficient"
    assert r.blocked is True and r.should_show is False
    assert r.score <= 40
    assert any("无证据" in c for c in r.caveats)


def test_single_evidence_has_caveat():
    r = sa.assess(evidence=[{"source": "filing"}])
    assert any("交叉验证" in c for c in r.caveats)


def test_low_quality_source_caveat():
    r = sa.assess(evidence=[{"source": "social"}, {"source": "social"}])
    assert any("可信度偏低" in c for c in r.caveats)


# --------------------------------------------------------------------------
# 各因子降分方向
# --------------------------------------------------------------------------
def test_freshness_decays():
    fresh = sa.assess(evidence=[{"source": "filing"}], freshness_days=1)
    stale = sa.assess(evidence=[{"source": "filing"}], freshness_days=200)
    assert fresh.score > stale.score
    assert any("时效性" in c for c in stale.caveats)


def test_disagreement_lowers_score():
    agree = sa.assess(evidence=[{"source": "filing"}], disagreement=0.0)
    split = sa.assess(evidence=[{"source": "filing"}], disagreement=0.9)
    assert agree.score > split.score
    assert any("分歧" in c for c in split.caveats)


def test_unresolved_lowers_score():
    a = sa.assess(evidence=[{"source": "filing"}], unresolved=0)
    b = sa.assess(evidence=[{"source": "filing"}], unresolved=5)
    assert a.score > b.score
    assert any("争议" in c for c in b.caveats)


def test_small_sample_caveat():
    r = sa.assess(evidence=[{"source": "filing"}], sample_size=10)
    assert any("样本量偏小" in c for c in r.caveats)


def test_oos_decay_caveat():
    r = sa.assess(evidence=[{"source": "filing"}], oos_decay=0.8)
    assert any("过拟合" in c for c in r.caveats)


def test_score_bounded():
    for kwargs in ({}, {"evidence": [{"source": "exchange"}] * 50,
                        "freshness_days": 0, "disagreement": 0,
                        "unresolved": 0, "sample_size": 10**6,
                        "oos_decay": 0, "self_report": 100}):
        r = sa.assess(**kwargs)
        assert 0.0 <= r.score <= 100.0


# --------------------------------------------------------------------------
# 辩论对接
# --------------------------------------------------------------------------
class _FakeEv:
    def __init__(self, source):
        self.source = source


class _FakeClaim:
    def __init__(self, evs):
        self.evidence = evs


class _FakeRound:
    def __init__(self, claims):
        self.claims = claims


class _FakeTranscript:
    def __init__(self, bull, bear, unresolved, rounds):
        self.bull_score = bull
        self.bear_score = bear
        self.unresolved = unresolved
        self.rounds = rounds


def test_from_debate_high_when_consensus():
    t = _FakeTranscript(0.8, 0.2, 0,
                        [_FakeRound([_FakeClaim([_FakeEv("exchange"),
                                                 _FakeEv("filing")])])])
    r = sa.from_debate(t, freshness_days=2, sample_size=300)
    assert r.band in ("medium", "high")
    assert r.evidence_count == 2


def test_from_debate_low_when_split():
    t = _FakeTranscript(0.5, 0.5, 4, [_FakeRound([_FakeClaim([_FakeEv("news")])])])
    r = sa.from_debate(t, freshness_days=120, sample_size=10)
    assert r.band in ("low", "insufficient")


def test_from_debate_tolerates_broken_object():
    r = sa.from_debate(object())
    assert isinstance(r, sa.ConfidenceReport)
    assert r.band == "insufficient"


# --------------------------------------------------------------------------
# 展示层
# --------------------------------------------------------------------------
def test_badge_text():
    r = sa.assess(evidence=[{"source": "exchange"}] * 5, freshness_days=1)
    assert sa.badge(r).startswith("置信度")
    assert "（" in sa.badge(r)


def test_annotate_never_adds_violation():
    r = sa.assess(evidence=[{"source": "exchange"}] * 5)
    txt = sa.annotate("该标的近期波动率上升", r)
    for bad in ("建议买入", "目标价", "必涨", "稳赚"):
        assert bad not in txt
    assert "不构成投资建议" in txt


def test_annotate_without_caveats():
    r = sa.assess(evidence=[{"source": "exchange"}] * 5, freshness_days=1,
                  disagreement=0, unresolved=0, sample_size=500, oos_decay=0)
    txt = sa.annotate("文本", r, with_caveats=False)
    assert "限制条件" not in txt


def test_to_ui_has_radar_and_flags():
    r = sa.assess(evidence=[{"source": "exchange"}] * 5)
    d = sa.to_ui(r)
    assert len(d["radar"]) == 7
    assert all(0 <= x["value"] <= 100 for x in d["radar"])
    assert isinstance(d["should_show"], bool)
    assert d["badge"]


def test_as_dict_serialisable():
    import json
    r = sa.assess(evidence=[{"source": "exchange"}])
    json.dumps(r.as_dict(), ensure_ascii=False)


if __name__ == "__main__":
    for name, fn in sorted(list(globals().items())):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok  {name}")
    print("ALL OK")
