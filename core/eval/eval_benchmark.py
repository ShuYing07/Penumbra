# -*- coding: utf-8 -*-
"""金融 AI 输出八维评测（模块一 · 参考 FORCE-Bench 8 维度）。

对 AI 分析文本从 8 个维度打分（确定性规则，不依赖 LLM，可单测）：
- accuracy  准确性：关键数值与 reference_data 是否一致（提取数字比对）
- citation  引用：是否标注数据来源/时间
- clarity   清晰度：句子结构、标点完整、无重复堆砌
- depth     深度：是否出现分析性词汇（趋势/原因/风险/对比…）
- evidence  有据可依：结论是否带数据支撑（含数字/来源）
- timeliness 时效性：是否标注数据时间或"最新/截至"等时效词
- relevance 相关性：是否回应用 query 的关键词
- structure 结构：是否含标题/分点/编号等结构化标记

返回 {accuracy, citation, clarity, depth, evidence, timeliness,
      relevance, structure, total, verdict}。
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

log = logging.getLogger("stockai.core.eval")

_DIMENSIONS = ["accuracy", "citation", "clarity", "depth",
               "evidence", "timeliness", "relevance", "structure"]

# 分析性/深度关键词（中文 + 英文）
_DEPTH_WORDS = [
    "趋势", "原因", "风险", "对比", "支撑", "压力", "金叉", "死叉",
    "基本面", "估值", "回测", "资金", "情绪", "宏观", "政策",
    "trend", "risk", "support", "resistance", "fundamental", "valuation",
]
# 时效性关键词
_TIME_WORDS = ["截至", "最新", "近", "日线", "周线", "月线", "202", "获取于",
               "as of", "latest", "updated", "2025", "2026"]
# 结构性标记
_STRUCT_MARKS = [":", "：", "1.", "2.", "3.", "①", "②", "③", "-", "·",
                 "#", "**", "步骤", "结论", "摘要", "一、", "二、", "三、",
                 "\n\n"]


def _num_hits(text: str) -> List[float]:
    """提取文本中的数值（含百分比/价格）。"""
    out: List[float] = []
    for m in re.finditer(r"\d+(?:\.\d+)?(?:%|倍|亿|万)?", text):
        try:
            out.append(float(m.group(0).rstrip("%倍亿万")))
        except ValueError:
            continue
    return out


def _accuracy_score(text: str, reference: Dict[str, Any]) -> float:
    """准确性：reference 里的关键数值在文本中出现的比例（归一）。"""
    if not reference:
        return 0.5   # 无参考数据时给中性分
    ref_nums = [v for v in reference.values()
                if isinstance(v, (int, float)) and v != 0]
    if not ref_nums:
        return 0.5
    hits = 0
    for rv in ref_nums:
        # 容忍 ±0.5% 的相对偏差
        r = abs(rv)
        if r <= 0:
            continue
        for n in _num_hits(text):
            if abs(n - r) / max(r, 1e-9) <= 0.005:
                hits += 1
                break
    return round(min(1.0, hits / len(ref_nums) + 0.3), 3)


def _citation_score(text: str) -> float:
    s = 0.0
    if re.search(r"(数据来源|来源[:：]|根据.{0,12}(数据|财报|报告|K线|公告))", text):
        s += 0.5
    if re.search(r"((获取于|截至|更新于).{0,10}\d{4})", text):
        s += 0.3
    if re.search(r"(AKShare|Tushare|yfinance|接口|财报|公告)", text):
        s += 0.2
    return round(min(1.0, s), 3)


def _clarity_score(text: str) -> float:
    t = (text or "").strip()
    if not t:
        return 0.0
    s = 0.6
    if len(t) >= 40:
        s += 0.2
    # 句子完整性：中文句号/叹号/问号出现
    if re.search(r"[。！？.!?]", t):
        s += 0.1
    if not re.search(r"(\u2026{2,}|。。。|重复)", t):
        s += 0.1
    return round(min(1.0, s), 3)


def _depth_score(text: str) -> float:
    hits = sum(1 for w in _DEPTH_WORDS if w in (text or ""))
    return round(min(1.0, 0.3 + hits * 0.12), 3)


def _evidence_score(text: str, reference: Dict[str, Any]) -> float:
    """有据可依：含数字 + 含来源线索。"""
    s = 0.0
    if len(_num_hits(text)) >= 3:
        s += 0.4
    elif _num_hits(text):
        s += 0.2
    if re.search(r"(数据来源|根据|依据|参考|数据)", text):
        s += 0.4
    if re.search(r"(近\d+日|过去\d+|回测|历史|区间)", text):
        s += 0.2
    return round(min(1.0, s), 3)


def _timeliness_score(text: str) -> float:
    t = (text or "")
    s = 0.0
    if re.search(r"20\d{2}[-/年.]\d{1,2}", t):
        s += 0.5
    if any(w in t for w in ("截至", "最新", "获取于", "更新于", "as of", "latest")):
        s += 0.3
    if any(w in t for w in ("日线", "周线", "月线", "近30日", "近90日")):
        s += 0.2
    return round(min(1.0, s), 3)


def _relevance_score(text: str, query: str) -> float:
    """相关性：query 关键词在回答中出现的覆盖度。"""
    q = (query or "").strip()
    if not q:
        return 0.5
    # 提取 query 关键词（2-4 字中文词 / 代码 / 英文词）
    tokens = set(re.findall(r"[A-Z]{1,6}\d{0,6}|[a-zA-Z]{3,}|\d{6}", q))
    tokens |= set(re.findall(r"[\u4e00-\u9fff]{2,6}", q))
    if not tokens:
        return 0.5
    hit = sum(1 for tk in tokens if tk in (text or ""))
    return round(min(1.0, hit / len(tokens) + 0.15), 3)


def _structure_score(text: str) -> float:
    t = (text or "")
    s = 0.0
    if any(m in t for m in ("#", "**", "一、", "1.", "摘要", "结论", "步骤")):
        s += 0.4
    if len(re.findall(r"[\n]", t)) >= 2:
        s += 0.3
    if any(m in t for m in (":", "：", "-", "·")):
        s += 0.3
    return round(min(1.0, s), 3)


def evaluate_analysis(analysis_text: str, query: str = "",
                      reference_data: Optional[Dict[str, Any]] = None) -> dict:
    """对 AI 输出 8 维打分。返回 {accuracy, ..., total, verdict}。"""
    reference = reference_data or {}
    text = analysis_text or ""
    if not text.strip():
        return {"scores": {d: 0.0 for d in _DIMENSIONS}, "total": 0.0,
                "verdict": "待改进", "dimensions": _DIMENSIONS}
    scores = {
        "accuracy": _accuracy_score(text, reference),
        "citation": _citation_score(text),
        "clarity": _clarity_score(text),
        "depth": _depth_score(text),
        "evidence": _evidence_score(text, reference),
        "timeliness": _timeliness_score(text),
        "relevance": _relevance_score(text, query),
        "structure": _structure_score(text),
    }
    total = round(sum(scores.values()) / 8.0, 3)
    verdict = ("优秀" if total >= 0.8 else "良好" if total >= 0.6
               else "合格" if total >= 0.4 else "待改进")
    return {"scores": scores, "total": total, "verdict": verdict,
            "dimensions": _DIMENSIONS}


if __name__ == "__main__":
    ref = {"close": 320.5, "rsi14": 62.9, "pe": 28.0}
    good = ("### 贵州茅台技术面摘要\n"
            "结论：RSI(14)=62.9，处于中性偏强区间。\n"
            "数据来源：AKShare日线接口（获取于 2026-09-28），近30日收盘价。\n"
            "风险：估值偏高，PE 28 倍高于白酒板块均值；下方支撑 310 附近。")
    bad = "我觉得这个股票还行，应该可以买点。"
    r1 = evaluate_analysis(good, "分析茅台技术面", ref)
    r2 = evaluate_analysis(bad, "分析茅台技术面", ref)
    assert r1["total"] > r2["total"], (r1["total"], r2["total"])
    assert r1["verdict"] in ("优秀", "良好")
    assert set(r1["scores"].keys()) == set(_DIMENSIONS)
    assert 0 <= r1["total"] <= 1
    # 空输入兜底
    r3 = evaluate_analysis("", "", None)
    assert r3["total"] == 0.0
    print(f"eval_benchmark self-check ok (good={r1['total']:.2f} "
          f"bad={r2['total']:.2f})")
