# -*- coding: utf-8 -*-
"""合规 AI 评审员（输出前最后一道独立审核）。

对齐香港金管局 GenA.I. 沙盒++ 的「AI 评审员」方案：在 AI 内容对外输出前，
由独立评审层审核其合规性——承诺收益、无风险暗示、夸大表述、荐股话术、
内幕暗示、免责声明缺失等。确定性规则兜底 + 可选 LLM 独立评审（失败自动降级）。
"""
from __future__ import annotations

import json
import logging
import re

log = logging.getLogger("stockai.compliance.reviewer")

# 评审规则表（可扩展；keyword 为正则）
_REVIEW_RULES = [
    {"id": "promise_return", "severity": "high", "label": "承诺收益",
     "regex": r"(必涨|必赚|保证.{0,4}(收益|盈利)|稳赚|包赚|翻倍|翻番|100%[赚涨]|百分百[赚涨]|躺赚|暴富)"},
    {"id": "no_risk", "severity": "high", "label": "无风险暗示",
     "regex": r"(无风险|零风险|保本|不会亏|只赚不亏|稳赢|稳赚不赔)"},
    {"id": "exaggeration", "severity": "medium", "label": "夸大表述",
     "regex": r"(确定性极高|绝对正确|万无一失|铁定|板上钉钉|必成)"},
    {"id": "stock_pick", "severity": "medium", "label": "荐股话术",
     "regex": r"(推荐买入|建议买入|强烈推荐|赶紧上车|跟上操作|带单|跟着买|满仓干|梭哈)"},
    {"id": "target_price", "severity": "high", "label": "目标价/买入评级",
     "regex": r"(目标价|目标位|上看\d+|看到\d+|买入评级|评级买入|维持买入|给到\d+元)"},
    {"id": "insider", "severity": "high", "label": "内幕/机密暗示",
     "regex": r"(内幕|庄家操盘|坐庄|消息面内部|独家渠道)"},
    {"id": "time_pressure", "severity": "low", "label": "制造时间压力",
     "regex": r"(最后机会|错过后悔|机不可失|不买就晚|马上行动)"},
]

_DISCLAIMER_OK = ("不构成投资建议", "仅供研究学习", "风险自负", "仅供参考")


def review_output(text: str, use_llm: bool = False,
                  timeout: int = 20) -> dict:
    """评审一段 AI 输出。返回 {passed, issues, score, disclaimer_ok, engine}。

    - passed: 无 high 级命中且免责声明存在（或文本极短无需声明）；
    - issues: 命中的规则明细（含建议）；
    - score: 0~100（合规度，命中 high 扣 40/条、medium 扣 20、low 扣 8，最低 0）。
    """
    t = str(text or "")
    issues: list[dict] = []
    for r in _REVIEW_RULES:
        m = re.search(r["regex"], t)
        if m:
            issues.append({
                "rule": r["id"], "severity": r["severity"], "label": r["label"],
                "keyword": m.group(0),
                "suggestion": _SUGGESTION.get(r["id"], "请修改为客观、中性的表述"),
            })

    disclaimer_ok = any(d in t for d in _DISCLAIMER_OK)
    if not disclaimer_ok and len(t) > 60:
        issues.append({"rule": "missing_disclaimer", "severity": "medium",
                       "label": "缺少风险免责声明",
                       "keyword": "",
                       "suggestion": "请在输出末尾注明「不构成投资建议，仅供研究学习」"})

    score = 100
    for i in issues:
        score -= {"high": 40, "medium": 20, "low": 8}.get(i["severity"], 10)
    score = max(0, min(100, score))

    engine = "rules"
    llm_review = None
    if use_llm:
        llm_review = _llm_review(t, timeout)
        if llm_review:
            engine = "rules+llm"

    high_hits = [i for i in issues if i["severity"] == "high"]
    passed = (not high_hits) and (disclaimer_ok or len(t) <= 60)
    return {
        "passed": passed,
        "issues": issues,
        "score": score,
        "disclaimer_ok": disclaimer_ok,
        "engine": engine,
        "llm_review": llm_review,
        "reviewed_at": __import__("time").time(),
    }


_SUGGESTION = {
    "promise_return": "收益承诺违规：改为客观历史数据描述，禁止对未来收益作保证",
    "no_risk": "无风险暗示违规：补充风险提示并删除绝对化表述",
    "exaggeration": "夸大表述：弱化为「仅供参考」的客观陈述",
    "stock_pick": "荐股话术：改为「研究对象展示」，不输出买入建议",
    "target_price": "目标价/评级：改为「当前数据对应的客观区间」，不输出目标价或买入评级",
    "insider": "内幕暗示：删除无法核实的消息面表述",
    "time_pressure": "时间压力话术：删除催单式表达",
}


def _llm_review(text: str, timeout: int) -> dict | None:
    """可选 LLM 独立评审（失败自动降级，绝不影响主流程）。"""
    try:
        from core.model_router import chat
        prompt = (
            "你是金融合规评审员。请评审以下 AI 生成内容是否存在合规风险：\n"
            "1) 承诺收益/无风险暗示 2) 荐股或夸大表述 3) 内幕暗示 4) 缺少免责声明。\n"
            "输出 JSON：{\"passed\": true/false, \"issues\": [\"...\"], \"suggestion\": \"...\"}\n"
            "内容如下：\n" + text[:1500])
        out = chat(prompt, system="只输出 JSON，不要多余文字", timeout=timeout)
        if not out:
            return None
        start = out.find("{")
        end = out.rfind("}")
        if start < 0 or end < start:
            return None
        obj = json.loads(out[start:end + 1])
        return {"passed": bool(obj.get("passed")), "issues": obj.get("issues") or [],
                "suggestion": obj.get("suggestion", "")}
    except Exception as e:  # noqa: BLE001
        log.debug("LLM 评审降级：%s", str(e)[:80])
        return None


if __name__ == "__main__":
    bad = "这只股票必涨，赶紧上车，无风险稳赚，跟庄家走！"
    good = "茅台近30日RSI为62，处于中性偏强区间。以上仅为客观数据展示，不构成投资建议。"
    print("bad:", json.dumps(review_output(bad), ensure_ascii=False, indent=1)[:400])
    print("good:", json.dumps(review_output(good), ensure_ascii=False, indent=1)[:400])
