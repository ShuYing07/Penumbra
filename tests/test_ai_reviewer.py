# -*- coding: utf-8 -*-
"""模块六 · 合规 AI 评审员测试。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("STOCKAI_MOCK", "1")

from security.ai_reviewer import review_output

PASS = 0


def ok(name: str):
    global PASS
    PASS += 1
    print(f"[ok] {name}")


def test_rejects_promise_and_no_risk():
    r = review_output("这只股票必涨，无风险稳赚，赶紧上车！")
    assert r["passed"] is False
    labels = {i["label"] for i in r["issues"]}
    assert "承诺收益" in labels and "无风险暗示" in labels
    assert r["score"] < 60
    ok("评审员拦截承诺收益/无风险话术")


def test_passes_objective_output_with_disclaimer():
    r = review_output("茅台近30日RSI为62，处于中性偏强区间。以上仅为客观数据展示，不构成投资建议。")
    assert r["passed"] is True
    assert r["disclaimer_ok"] is True
    assert r["score"] >= 80
    ok("客观输出+免责声明通过评审")


def test_missing_disclaimer_flagged():
    r = review_output("根据2026年第二季度财报，该公司营业收入同比增长15.2%，归母净利润增长18.4%，"
                      "毛利率维持在91%的高位，净资产收益率（ROE）为25.3%，经营性现金流为正，"
                      "资产负债率有所下降。以上数据为基本面客观信息汇总。")
    assert any(i["rule"] == "missing_disclaimer" for i in r["issues"])
    assert r["score"] < 100
    ok("长文本缺少免责声明被标注")


def test_short_text_without_disclaimer_ok():
    r = review_output("加载完成")
    assert r["passed"] is True  # 短文本无需免责声明
    ok("短文本不受免责声明要求约束")


def test_insider_hint_caught():
    r = review_output("我通过内幕渠道得知，庄家下周要拉升这只股票。")
    assert any(i["rule"] == "insider" for i in r["issues"])
    ok("内幕暗示命中")


def test_score_floor():
    r = review_output("必涨稳赚无风险保本内幕坐庄板上钉钉，赶紧上车！")
    assert 0 <= r["score"] <= 100
    assert r["score"] == 0 or r["score"] < 40
    ok("评分有界且高风险文本得分极低")


def test_llm_review_degrade_safe():
    r = review_output("测试内容，仅供参考", use_llm=True, timeout=3)
    assert r["engine"] in ("rules", "rules+llm")
    ok("LLM 评审失败自动降级，不抛异常")


if __name__ == "__main__":
    test_rejects_promise_and_no_risk()
    test_passes_objective_output_with_disclaimer()
    test_missing_disclaimer_flagged()
    test_short_text_without_disclaimer_ok()
    test_insider_hint_caught()
    test_score_floor()
    test_llm_review_degrade_safe()
    print(f"\nALL PASS ({PASS})")
