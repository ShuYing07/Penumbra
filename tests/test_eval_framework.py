# -*- coding: utf-8 -*-
"""模块一 · 金融智能体评测体系（财跃星辰「资本-资产匹配」框架）unit tests。

覆盖：四维评分、六大维度匹配判定、主动拒答合格、评测任务生成、空输入兜底。
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("STOCKAI_MOCK", "1")

from core.eval.eval_framework import (  # noqa: E402
    ASSET_CLASSES, CAPITAL_PROFILES, FITNESS_DIMENSIONS,
    build_eval_tasks, detect_asset_mention, evaluate_framework,
    match_capital_to_asset, refusal_ok,
)

REF = {"rsi14": 62.9, "pe": 28.0}


def _profile(pid):
    return next(p for p in CAPITAL_PROFILES if p["id"] == pid)


def test_dimensions_are_six():
    assert len(FITNESS_DIMENSIONS) == 6
    assert set(FITNESS_DIMENSIONS) == {"收益", "风险", "期限", "流动性",
                                       "收益结构", "约束"}


def test_profiles_and_assets_cover_six_dims():
    for p in CAPITAL_PROFILES:
        for d in FITNESS_DIMENSIONS:
            assert p.get(d), f"画像 {p['id']} 缺维度 {d}"
    for a in ASSET_CLASSES:
        for d in FITNESS_DIMENSIONS:
            assert a.get(d), f"资产 {a['id']} 缺维度 {d}"


def test_match_emergency_vs_assets():
    """短期应急资金：货币基金匹配，股票不匹配（判断不匹配=不合格答案）。"""
    emergency = _profile("emergency")
    mm = next(a for a in ASSET_CLASSES if a["id"] == "money_market")
    eq = next(a for a in ASSET_CLASSES if a["id"] == "equity")
    assert match_capital_to_asset(emergency, mm)["match"] is True
    assert match_capital_to_asset(emergency, eq)["match"] is False
    # 股票期限/风险硬冲突
    r = match_capital_to_asset(emergency, eq)
    assert "期限" in r["mismatched_dims"] and "风险" in r["mismatched_dims"]


def test_refusal_ok():
    assert refusal_ok("基于现有信息无法判断，不构成投资建议。")
    assert refusal_ok("信息不足，拒绝给出结论。")
    assert not refusal_ok("建议配置货币基金，风险较低。")


def test_detect_asset_mention():
    assert "equity" in detect_asset_mention("建议关注这只股票")
    assert "gold" in detect_asset_mention("配置黄金对冲")
    assert detect_asset_mention("分析一下宏观") == []


def test_evaluate_mismatched_low():
    """短期资金配股票 + 目标价/翻倍 → 匹配不匹配 + 合规拦截 → 低分。"""
    r = evaluate_framework(
        "建议买入股票，目标价 2000 元，预计翻倍。这只股短期会涨很多。",
        "3个月后要用的钱怎么配", _profile("emergency"), REF)
    assert r["refused"] is False
    assert r["match_verdict"] == "mismatched"
    assert r["scores"]["fitness"] < 0.5
    assert r["scores"]["compliance"] < 0.5


def test_evaluate_matched_good():
    """应急资金配货币基金/短债 + 免责声明 → 匹配 + 合规 → 高分。"""
    r = evaluate_framework(
        "应急资金应以流动性优先，建议配置货币基金/短债，"
        "该类别波动极低、随时可取；不构成投资建议，风险自担。",
        "3个月后要用的钱怎么配", _profile("emergency"), REF)
    assert r["match_verdict"] == "matched"
    assert r["scores"]["fitness"] >= 0.7
    assert r["scores"]["compliance"] >= 0.8
    assert r["total"] >= 0.5


def test_evaluate_refusal_qualified():
    """主动拒答视为合格答案（不扣适配分）。"""
    r = evaluate_framework(
        "基于现有信息无法判断该资金的适配资产，建议结合个人风险承受"
        "能力咨询专业机构；不构成投资建议。",
        "怎么配", _profile("emergency"), REF)
    assert r["refused"] is True
    assert r["match_verdict"] == "refused_ok"
    assert r["scores"]["fitness"] >= 0.8


def test_evaluate_no_profile_neutral():
    r = evaluate_framework("建议配置货币基金，波动极低。", "", None, None)
    assert r["scores"]["fitness"] == 0.5
    assert r["match_verdict"] == "unknown"


def test_evaluate_empty_input():
    r = evaluate_framework("", "", None, None)
    assert r["total"] == 0.0 and r["verdict"] == "待改进"
    assert r["match_verdict"] == "unknown"
    assert all(v == 0.0 for v in r["scores"].values())


def test_build_eval_tasks():
    tasks = build_eval_tasks()
    assert len(tasks) == 4
    assert all(t["accept_refusal"] for t in tasks)
    assert all(t["capital_profile"]["id"] for t in tasks)
    assert all(len(t["candidates"]) == len(ASSET_CLASSES) for t in tasks)


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"[ok] {fn.__name__}")
    print(f"\nALL PASS ({len(fns)})")
