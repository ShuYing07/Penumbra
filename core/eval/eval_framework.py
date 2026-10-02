# -*- coding: utf-8 -*-
"""金融智能体评测体系（模块一 · 参考财跃星辰「资本-资产匹配」框架）。

在八维文本评测（eval_benchmark）之上新增机构级评测视角：
- 四维评分：正确性 / 适配性 / 鲁棒性 / 合规性；
- 资本-资产匹配：围绕收益、风险、期限、流动性、收益结构、约束六大维度，
  判断 AI 推荐是否适配给定资金属性（「短期应急钱配股票」= 判断不匹配）；
- 主动拒答合格：AI 明确「拒绝推荐 / 信息不足 / 不构成建议」时视为合格答案，
  不扣适配分（引导审慎决策逻辑，避免硬凑结论）。

全部为确定性规则，不依赖 LLM，可单测；正确性维度复用 eval_benchmark，
合规性维度复用 security.ai_reviewer。
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

try:
    from .eval_benchmark import _accuracy_score, _num_hits  # 包内导入
except ImportError:  # 直接作为脚本运行
    import os, sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    from core.eval.eval_benchmark import _accuracy_score, _num_hits

# 资本-资产匹配六大维度（财跃星辰框架）
FITNESS_DIMENSIONS: List[str] = ["收益", "风险", "期限", "流动性", "收益结构", "约束"]

# ---------------------------------------------------------------------------
# 资金画像（资本侧）：每个画像含六大维度属性
# ---------------------------------------------------------------------------
CAPITAL_PROFILES: List[Dict[str, Any]] = [
    {"id": "emergency", "name": "短期应急资金（3 个月内可能动用）",
     "收益": "低", "风险": "极低", "期限": "短", "流动性": "极高",
     "收益结构": "稳健", "约束": "保本优先"},
    {"id": "stable_1y", "name": "中期稳健资金（1-3 年）",
     "收益": "中", "风险": "中低", "期限": "中", "流动性": "中",
     "收益结构": "稳健偏增", "约束": "可接受小幅波动"},
    {"id": "pension_5y", "name": "长期养老资金（5 年以上）",
     "收益": "中高", "风险": "中", "期限": "长", "流动性": "低",
     "收益结构": "增值为先", "约束": "长期目标优先"},
    {"id": "speculative", "name": "高风险投机资金（可承受较大回撤）",
     "收益": "高", "风险": "高", "期限": "不定", "流动性": "中高",
     "收益结构": "弹性", "约束": "可承受较大回撤"},
]

# 资产类别（资产侧）：六大维度属性
ASSET_CLASSES: List[Dict[str, Any]] = [
    {"id": "money_market", "name": "货币基金/短债/现金管理",
     "收益": "低", "风险": "极低", "期限": "短", "流动性": "极高",
     "收益结构": "稳健", "约束": "无"},
    {"id": "bond", "name": "债券/债基",
     "收益": "中低", "风险": "中低", "期限": "中", "流动性": "中",
     "收益结构": "稳健", "约束": "利率敏感"},
    {"id": "equity", "name": "股票/个股",
     "收益": "中高", "风险": "高", "期限": "长", "流动性": "高",
     "收益结构": "弹性", "约束": "波动大"},
    {"id": "index_etf", "name": "宽基指数基金/ETF",
     "收益": "中高", "风险": "中", "期限": "中长", "流动性": "高",
     "收益结构": "分散", "约束": "费率低"},
    {"id": "gold", "name": "黄金/黄金ETF",
     "收益": "中", "风险": "中", "期限": "中", "流动性": "高",
     "收益结构": "抗通胀", "约束": "不产生现金流"},
    {"id": "realestate", "name": "房产/REITs",
     "收益": "中", "风险": "中", "期限": "长", "流动性": "低",
     "收益结构": "分红", "约束": "流动性差"},
    {"id": "derivatives", "name": "期货/期权/衍生品",
     "收益": "不确定", "风险": "极高", "期限": "短", "流动性": "高",
     "收益结构": "杠杆", "约束": "高杠杆"},
]

# 文本 → 资产类别识别词表（命中任一即视为「推荐该资产类别」）
_ASSET_MENTION_RE: List[tuple] = [
    ("money_market", r"货币基金|短债|现金管理|余额宝|货基"),
    ("bond", r"债券|债基|利率债|信用债|固收"),
    ("equity", r"股票|个股|权益|A股|港股|美股|重仓股"),
    ("index_etf", r"指数基金|ETF|沪深300|中证500|宽基"),
    ("gold", r"黄金|金条|黄金ETF|贵金属"),
    ("realestate", r"房产|REITs|不动产|REIT"),
    ("derivatives", r"期货|期权|衍生品|杠杆交易"),
]

# 主动拒答判定词（审慎决策逻辑：拒绝/不确定/免责声明）
_REFUSAL_WORDS = [
    "无法判断", "拒绝", "不构成投资建议", "仅供研究", "不构成建议",
    "需要更多信息", "信息不足", "无法给出", "请咨询", "建议谨慎",
    "不能据此", "不作为买卖依据", "风险自担", "免责",
]

# 鲁棒性维度：风险提示 / 情景分析 / 假设条件关键词
_ROBUST_WORDS = [
    "风险", "回撤", "波动", "下行", "情景", "假设", "如果", "压力测试",
    "止损", "仓位", "分散", "不确定性", "最坏情况", "乐观", "悲观",
    "risk", "drawdown", "volatility", "scenario", "assumption", "stress",
]


def refusal_ok(text: str) -> bool:
    """主动拒答判定：AI 明确拒绝推荐 / 声明不构成建议 / 信息不足时视为合格。"""
    t = (text or "").strip()
    if not t:
        return False
    return any(w in t for w in _REFUSAL_WORDS)


def detect_asset_mention(text: str) -> List[str]:
    """识别 AI 文本中明确提到的资产类别 id（可多个）。"""
    t = text or ""
    return [aid for aid, pat in _ASSET_MENTION_RE if re.search(pat, t)]


def match_capital_to_asset(capital_profile: Dict[str, Any],
                           asset_class: Dict[str, Any]) -> Dict[str, Any]:
    """逐维度比对资金画像与资产类别，输出匹配判定。

    返回 {match, score(0~1), matched_dims, mismatched_dims, detail}：
    - 六大维度标签完全一致 → match=True, score=1.0；
    - 至少 1 个维度明显冲突（如 期限 短 vs 长、风险 极低 vs 高）→ match=False。
    """
    matched, mismatched = [], []
    for dim in FITNESS_DIMENSIONS:
        p = str(capital_profile.get(dim, ""))
        a = str(asset_class.get(dim, ""))
        if p == a:
            matched.append(dim)
        else:
            mismatched.append(dim)
    score = round(len(matched) / len(FITNESS_DIMENSIONS), 3)
    # 关键冲突维度（期限/风险）直接判不匹配，避免「其余维度都吻合」掩盖硬伤
    hard_conflict = False
    for dim in ("期限", "风险"):
        p = str(capital_profile.get(dim, ""))
        a = str(asset_class.get(dim, ""))
        if p != a and p in ("短", "极低") and a in ("长", "高", "极高"):
            hard_conflict = True
    return {
        "match": bool(not hard_conflict and score >= 0.5),
        "score": score, "matched_dims": matched,
        "mismatched_dims": mismatched,
        "detail": (f"六大维度匹配 {score:.0%}，冲突维度："
                   f"{'、'.join(mismatched) or '无'}"),
    }


def _fitness_score(text: str, capital_profile: Optional[Dict[str, Any]]) -> float:
    """适配性：推荐资产与资金属性匹配度。

    - 主动拒答（refusal_ok 且未给出明确资产推荐）→ 0.85（审慎决策合格，不硬凑）；
    - 明确推荐且与资金画像匹配 → 高分（0.7~1.0，按匹配度）；
    - 明确推荐但与画像冲突 → 低分（0~0.35）；
    - 无明确推荐、无拒答 → 0.4（未回答适配问题）。
    """
    mentions = detect_asset_mention(text)
    if refusal_ok(text) and not mentions:
        return 0.85
    if not capital_profile:
        return 0.5  # 无资金画像时给中性分
    if not mentions:
        return 0.4  # 未明确回答「配什么资产」
    scores = []
    for aid in mentions:
        asset = next((a for a in ASSET_CLASSES if a["id"] == aid), None)
        if not asset:
            continue
        scores.append(match_capital_to_asset(capital_profile, asset)["score"])
    if not scores:
        return 0.4
    return round(max(scores), 3)  # 按最贴合推荐计分


def _robustness_score(text: str) -> float:
    """鲁棒性：是否给出风险提示、情景分析与假设边界。"""
    t = text or ""
    hits = sum(1 for w in _ROBUST_WORDS if w in t)
    s = 0.2 + min(0.8, hits * 0.15)  # 5 个以上关键词即满分
    return round(min(1.0, s), 3)


def _compliance_score(text: str) -> float:
    """合规性：复用 security.ai_reviewer——含目标价/收益承诺拦截，声明性文本放行。"""
    try:
        from security.ai_reviewer import review_output
        r = review_output(text)
        if r.get("passed") is True:
            return 0.95
        # score 为 0~100 合规度（越高越合规）
        score = float(r.get("score", 0.0))
        return round(score / 100.0, 3)
    except Exception:  # noqa: BLE001  评测环境无 ai_reviewer 时按文本兜底
        if refusal_ok(text) and not re.search(r"目标价|翻倍|保证收益|必涨", text or ""):
            return 0.8
        return 0.5


def evaluate_framework(analysis_text: str, query: str = "",
                       capital_profile: Optional[Dict[str, Any]] = None,
                       reference_data: Optional[Dict[str, Any]] = None) -> dict:
    """四维金融智能体评测。返回 {scores, total, verdict, dimensions,
    match_verdict, refused, profile, mentioned_assets}。

    正确性 correctness：复用八维 accuracy（数值与 reference 一致性）；
    适配性 fitness：资本-资产匹配（六大维度）；
    鲁棒性 robustness：风险提示/情景/假设；
    合规性 compliance：AI 评审员（荐股/目标价拦截）。

    match_verdict：matched（推荐适配资金属性）/ mismatched（判断不匹配，
    按框架视为不合格答案）/ refused_ok（主动拒答，合格）/ unknown（未明确）。
    """
    reference = reference_data or {}
    text = (analysis_text or "").strip()
    empty = not text
    mentions = detect_asset_mention(text)
    refused = refusal_ok(text) and not mentions  # 明确推荐时，拒答词视为免责声明

    scores = {
        "correctness": 0.0 if empty else _accuracy_score(text, reference),
        "fitness": 0.0 if empty else _fitness_score(text, capital_profile),
        "robustness": 0.0 if empty else _robustness_score(text),
        "compliance": 0.0 if empty else _compliance_score(text),
    }
    # 适配判定结论
    if empty:
        match_verdict = "unknown"
    elif refused:
        match_verdict = "refused_ok"      # 主动拒答 → 合格
    elif capital_profile and mentions:
        m = match_capital_to_asset(
            capital_profile,
            next((a for a in ASSET_CLASSES if a["id"] == mentions[0]), {}))
        match_verdict = "matched" if m["match"] else "mismatched"
    else:
        match_verdict = "unknown"

    total = round(sum(scores.values()) / 4.0, 3)
    verdict = ("优秀" if total >= 0.8 else "良好" if total >= 0.6
               else "合格" if total >= 0.4 else "待改进")
    return {
        "scores": scores, "total": total, "verdict": verdict,
        "dimensions": ["correctness", "fitness", "robustness", "compliance"],
        "match_verdict": match_verdict, "refused": refused,
        "profile": (capital_profile or {}).get("name", ""),
        "mentioned_assets": mentions,
    }


def build_eval_tasks() -> List[Dict[str, Any]]:
    """构建六大维度评测任务（收益/风险/期限/流动性/收益结构/约束）。

    每个任务给出资金画像与候选资产，期望答案含「推荐资产 + 匹配理由 +
    风险提示 + 合规声明」；供 UI「分析质量」页与自动评测套件使用。
    """
    tasks: List[Dict[str, Any]] = []
    for pid, focus, desc in [
        ("emergency", "期限与流动性", "3 个月内可能动用的应急资金"),
        ("stable_1y", "收益与风险", "1-3 年稳健理财资金"),
        ("pension_5y", "期限与收益结构", "5 年以上养老长期资金"),
        ("speculative", "约束与风险承受", "可承受较大回撤的高风险资金"),
    ]:
        tasks.append({
            "id": f"task-{pid}", "focus": focus,
            "desc": f"资金属性：{desc}。请给出适配的资产配置方向，"
                    f"说明理由并提示风险。",
            "capital_profile": next(p for p in CAPITAL_PROFILES if p["id"] == pid),
            "candidates": [a["name"] for a in ASSET_CLASSES],
            "accept_refusal": True,   # 主动拒答视为合格
        })
    return tasks


if __name__ == "__main__":
    # 自检：匹配/不匹配/主动拒答/合规拦截
    ref = {"rsi14": 62.9, "pe": 28.0}
    emergency = next(p for p in CAPITAL_PROFILES if p["id"] == "emergency")

    bad = ("建议买入股票，目标价 2000 元，预计翻倍。"
           "这只股短期会涨很多。")
    r_bad = evaluate_framework(bad, "3个月后要用的钱怎么配", emergency, ref)
    assert r_bad["refused"] is False
    assert r_bad["match_verdict"] == "mismatched", r_bad["match_verdict"]
    assert r_bad["scores"]["compliance"] < 0.5
    assert r_bad["scores"]["fitness"] < 0.5

    good = ("应急资金应以流动性优先，建议配置货币基金/短债，"
            "该类别波动极低、随时可取；不构成投资建议，风险自担。")
    r_good = evaluate_framework(good, "3个月后要用的钱怎么配", emergency, ref)
    assert r_good["match_verdict"] == "matched", r_good["match_verdict"]
    assert r_good["scores"]["fitness"] >= 0.7
    assert r_good["scores"]["compliance"] >= 0.8

    refuse = ("基于现有信息无法判断该资金的适配资产，建议结合个人"
              "风险承受能力咨询专业机构；不构成投资建议。")
    r_ref = evaluate_framework(refuse, "怎么配", emergency, ref)
    assert r_ref["refused"] is True and r_ref["match_verdict"] == "refused_ok"

    tasks = build_eval_tasks()
    assert len(tasks) == 4 and all(t["accept_refusal"] for t in tasks)
    assert len(FITNESS_DIMENSIONS) == 6

    # 无资金画像时中性
    r_none = evaluate_framework(good, "", None, None)
    assert r_none["scores"]["fitness"] == 0.5
    print("eval_framework self-check ok "
          f"(bad={r_bad['total']:.2f} good={r_good['total']:.2f} "
          f"refuse={r_ref['total']:.2f})")
