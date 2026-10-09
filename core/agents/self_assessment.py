# -*- coding: utf-8 -*-
"""Agent 结论级置信度自评（self-assessment / confidence annotation）。

为什么需要
----------
大模型最爱犯的错不是算错，而是**用同样的语气说确定的事和不确定的事**。
「我认为」三个字后面，可能是 10 条交叉验证过的证据，也可能只是模型在补全句子。

本模块把「有多确定」这件事**显式化**：每条结论在下发前必须算出置信度，
连同**限制条件（caveats）**一起展示；置信度不足的结论不允许单独呈现。

设计原则
--------
1. **可计算**：全部由证据数量/来源等级/新鲜度/分歧度/样本量等客观量驱动，
   不依赖 LLM 自报（可选接入，仅作参考项，权重最低）。
2. **可解释**：输出每个因子的贡献值，用户能看懂"为什么是这个分"。
3. **可门禁**：给出 should_show / needs_review / blocked 三级处置建议。
4. **合规友好**：置信度低时自动追加提示语，绝不把不确定说成确定。

颜色约定：涨=#00C853 / 跌=#FF1744 只用于涨跌语义；
置信度一律用**中性色**（蓝/橙/灰），不占用涨跌红绿。
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

log = logging.getLogger("stockai.agents.selfassess")

# ---------------------------------------------------------------------------
# 置信度分档
# ---------------------------------------------------------------------------
BANDS: List[Dict[str, Any]] = [
    {"id": "high", "name": "高", "min": 75, "color": "#1976D2",
     "action": "show", "hint": "证据充分，可直接展示"},
    {"id": "medium", "name": "中", "min": 55, "color": "#F9A825",
     "action": "show_with_caveat", "hint": "需附加限制条件后展示"},
    {"id": "low", "name": "低", "min": 35, "color": "#EF6C00",
     "action": "needs_review", "hint": "建议人工复核后再展示"},
    {"id": "insufficient", "name": "不足", "min": 0, "color": "#9E9E9E",
     "action": "block", "hint": "不应单独展示，仅可作为研究线索"},
]

# 来源可信度分层（越高越可信）
SOURCE_TIERS: Dict[str, float] = {
    "exchange": 1.00,     # 交易所公告/问询函
    "filing": 0.95,       # 定期报告/招股书
    "official": 0.90,     # 公司官网/投资者关系
    "regulator": 0.90,    # 监管披露
    "financial": 0.80,    # 结构化财务数据
    "market": 0.70,       # 行情数据
    "research": 0.60,     # 券商研报
    "news": 0.50,         # 新闻
    "social": 0.30,       # 社交/论坛
    "model": 0.40,        # 模型推断（无外部证据）
    "unknown": 0.35,
}
_DEFAULT_TIER = 0.35


def tier_of(source: str) -> float:
    """来源字符串 → 可信度（模糊匹配，未识别按 unknown）。"""
    s = str(source or "").lower()
    for k, v in SOURCE_TIERS.items():
        if k in s:
            return v
    return _DEFAULT_TIER


@dataclass
class Factor:
    """置信度驱动因子。"""
    key: str
    name: str
    weight: float          # 0~1，所有因子权重归一化
    raw: float             # 原始输入（各因子自带量纲）
    normalized: float      # 归一化到 0~1（越高越好）
    contribution: float    # 归一化 × 权重 × 100

    def as_dict(self) -> Dict[str, Any]:
        return {"key": self.key, "name": self.name, "weight": self.weight,
                "raw": self.raw, "normalized": round(self.normalized, 3),
                "contribution": round(self.contribution, 2)}


@dataclass
class ConfidenceReport:
    """结论置信度报告。"""
    score: float                                   # 0~100
    band: str                                      # high/medium/low/insufficient
    band_name: str
    color: str
    action: str                                    # show/show_with_caveat/needs_review/block
    factors: List[Factor] = field(default_factory=list)
    caveats: List[str] = field(default_factory=list)
    evidence_count: int = 0
    hint: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {"score": round(self.score, 1), "band": self.band,
                "band_name": self.band_name, "color": self.color,
                "action": self.action, "hint": self.hint,
                "evidence_count": self.evidence_count,
                "factors": [f.as_dict() for f in self.factors],
                "caveats": list(self.caveats)}

    # ---- 便捷判定 ----
    @property
    def should_show(self) -> bool:
        return self.action in ("show", "show_with_caveat")

    @property
    def needs_review(self) -> bool:
        return self.action == "needs_review"

    @property
    def blocked(self) -> bool:
        return self.action == "block"


# ---------------------------------------------------------------------------
# 因子归一化
# ---------------------------------------------------------------------------
def _sat(x: float, k: float = 1.0) -> float:
    """饱和函数：x/(x+k)，把无上界的计数压到 0~1。"""
    x = max(0.0, float(x))
    return x / (x + k)


def _norm_01(x: float) -> float:
    return min(1.0, max(0.0, float(x)))


def assess(evidence: Optional[Sequence[Dict[str, Any]]] = None,
           freshness_days: Optional[float] = None,
           disagreement: Optional[float] = None,
           unresolved: int = 0,
           sample_size: Optional[int] = None,
           oos_decay: Optional[float] = None,
           self_report: Optional[float] = None,
           extra_caveats: Optional[Sequence[str]] = None,
           weights: Optional[Dict[str, float]] = None) -> ConfidenceReport:
    """计算一条结论的置信度。

    Args:
        evidence: 证据列表，元素含 ``source``（来源）可选 ``weight``；
        freshness_days: 最新证据距今天数（越小越好，None=未知按中性）；
        disagreement: 多空/多模型分歧度 0~1（越大越不确定）；
        unresolved: 辩论后仍未解决的争议条数；
        sample_size: 样本量（回测 bar 数 / 观测样本数）；
        oos_decay: 样本外相对样本内的衰减比例 0~1（越大越不稳定）；
        self_report: 模型自报置信度 0~100（权重最低，仅参考）；
        extra_caveats: 外部追加的限制条件；
        weights: 自定义因子权重（缺省用内置）。

    Returns:
        ConfidenceReport
    """
    ev = list(evidence or [])
    caveats: List[str] = list(extra_caveats or [])

    # --- 证据充分性（数量 × 来源质量）---
    if ev:
        quality = [float(e.get("weight", tier_of(e.get("source", "")))) for e in ev]
        avg_q = sum(quality) / len(quality)
        ev_raw = float(len(ev))
        ev_norm = (0.6 * _sat(ev_raw, k=3.0) + 0.4 * _norm_01(avg_q))
        if len(ev) < 2:
            caveats.append("仅有一条证据支撑，未形成交叉验证")
        if avg_q < 0.5:
            caveats.append("证据来源可信度偏低（含社交/推断类来源）")
    else:
        ev_norm = 0.0
        caveats.append("无外部证据，结论仅由模型推断得出")

    # --- 新鲜度 ---
    if freshness_days is None:
        fresh_norm = 0.6                      # 未知 → 中性偏保守
    else:
        fresh_norm = math.exp(-max(0.0, freshness_days) / 30.0)   # 30 天半衰
        if freshness_days > 90:
            caveats.append(f"最新证据距今 {int(freshness_days)} 天，时效性不足")
        elif freshness_days > 30:
            caveats.append(f"证据距今 {int(freshness_days)} 天，请核对最新披露")

    # --- 一致性（分歧度越低越好）---
    if disagreement is None:
        consist_norm = 0.7
    else:
        consist_norm = 1.0 - _norm_01(disagreement)
        if disagreement >= 0.5:
            caveats.append("多空/多模型分歧较大，结论方向未收敛")

    # --- 争议收敛（未决争议）---
    unres_raw = float(max(0, int(unresolved)))
    unres_norm = 1.0 - _sat(unres_raw, k=2.0)
    if unres_raw >= 2:
        caveats.append(f"仍有 {int(unres_raw)} 项争议未被反驳，结论存在未闭合缺口")

    # --- 样本量 ---
    if sample_size is None:
        sample_norm = 0.6
    else:
        sample_norm = _sat(float(sample_size), k=60.0)
        if sample_size < 30:
            caveats.append(f"样本量偏小（{int(sample_size)}），统计结论不稳健")

    # --- 稳健性（样本外衰减）---
    if oos_decay is None:
        stable_norm = 0.7
    else:
        stable_norm = 1.0 - _norm_01(oos_decay)
        if oos_decay >= 0.5:
            caveats.append("样本外表现衰减明显，存在过拟合风险")

    # --- 模型自报（权重最低）---
    if self_report is None:
        self_norm = 0.6
    else:
        self_norm = _norm_01(float(self_report) / 100.0)

    raw_factors = [
        Factor("evidence", "证据充分性", 0.30, len(ev), ev_norm, 0.0),
        Factor("freshness", "时效性", 0.15,
               freshness_days if freshness_days is not None else -1, fresh_norm, 0.0),
        Factor("consistency", "一致性", 0.15,
               disagreement if disagreement is not None else -1, consist_norm, 0.0),
        Factor("convergence", "争议收敛", 0.10, unres_raw, unres_norm, 0.0),
        Factor("sample", "样本量", 0.10,
               sample_size if sample_size is not None else -1, sample_norm, 0.0),
        Factor("stability", "稳健性", 0.10,
               oos_decay if oos_decay is not None else -1, stable_norm, 0.0),
        Factor("self_report", "模型自评", 0.10,
               self_report if self_report is not None else -1, self_norm, 0.0),
    ]

    w = dict(weights or {})
    total_w = sum(w.get(f.key, f.weight) for f in raw_factors) or 1.0
    for f in raw_factors:
        f.weight = w.get(f.key, f.weight) / total_w
        f.contribution = f.normalized * f.weight * 100.0

    score = sum(f.contribution for f in raw_factors)
    # 硬约束：无证据 ⇒ 直接判「不足」（与辩论引擎「无证据不成主张」同律）
    if not ev:
        score = min(score, 34.0)
        caveats.append("无证据支撑，置信度强制判为「不足」，不得单独展示")
    score = round(min(100.0, max(0.0, score)), 1)

    band = next(b for b in BANDS if score >= b["min"])
    if not ev:
        band = next(b for b in BANDS if b["id"] == "insufficient")
    return ConfidenceReport(
        score=score, band=band["id"], band_name=band["name"],
        color=band["color"], action=band["action"],
        factors=raw_factors, caveats=caveats,
        evidence_count=len(ev), hint=band["hint"])


# ---------------------------------------------------------------------------
# 与辩论引擎对接
# ---------------------------------------------------------------------------
def from_debate(transcript: Any,
                freshness_days: Optional[float] = None,
                sample_size: Optional[int] = None) -> ConfidenceReport:
    """由辩论结果推导置信度（分歧度 = 多空分差归一化）。"""
    try:
        bull = float(getattr(transcript, "bull_score", 0.0))
        bear = float(getattr(transcript, "bear_score", 0.0))
        unresolved = len(getattr(transcript, "unresolved", []) or [])
        claims = []
        for r in getattr(transcript, "rounds", []) or []:
            for c in getattr(r, "claims", []) or []:
                for e in getattr(c, "evidence", []) or []:
                    src = getattr(e, "source", "") if not isinstance(e, dict) \
                        else e.get("source", "")
                    claims.append({"source": src})
    except Exception as e:  # noqa: BLE001
        log.debug("辩论结构解析失败：%s", e)
        bull = bear = 0.0
        unresolved = 0
        claims = []

    span = max(bull, bear, 1e-9)
    disagreement = abs(bull - bear) / span          # 越接近 1 分歧越大
    return assess(evidence=claims, freshness_days=freshness_days,
                  disagreement=disagreement, unresolved=unresolved,
                  sample_size=sample_size)


# ---------------------------------------------------------------------------
# 展示层
# ---------------------------------------------------------------------------
def badge(report: ConfidenceReport) -> str:
    """一行徽标文本，如「置信度 72（高）」。"""
    return f"置信度 {report.score:.0f}（{report.band_name}）"


def annotate(text: str, report: ConfidenceReport,
             with_caveats: bool = True) -> str:
    """把置信度与限制条件追加到结论尾部（合规展示用）。

    注意：只做**风险揭示**，绝不添加买入/目标价等违规内容。
    """
    head = f"\n\n—— {badge(report)}｜{report.hint}"
    if not with_caveats or not report.caveats:
        return (text or "") + head + "\n（本内容为客观数据分析，不构成投资建议）"
    body = "\n".join(f"· {c}" for c in report.caveats)
    return (text or "") + head + "\n限制条件：\n" + body + \
        "\n（本内容为客观数据分析，不构成投资建议）"


def to_ui(report: ConfidenceReport) -> Dict[str, Any]:
    """给 UI 的扁平结构（含雷达图所需的 name/value 对）。"""
    d = report.as_dict()
    d["radar"] = [{"name": f.name, "value": round(f.normalized * 100, 1)}
                  for f in report.factors]
    d["badge"] = badge(report)
    d["should_show"] = report.should_show
    d["needs_review"] = report.needs_review
    d["blocked"] = report.blocked
    return d


if __name__ == "__main__":
    strong = assess(evidence=[{"source": "exchange"}, {"source": "filing"},
                              {"source": "financial"}, {"source": "market"}],
                    freshness_days=3, disagreement=0.1, unresolved=0,
                    sample_size=500, oos_decay=0.05, self_report=85)
    assert strong.score >= 75 and strong.band == "high", strong.as_dict()
    assert strong.should_show and not strong.blocked

    weak = assess(evidence=[], sample_size=5)
    assert weak.band == "insufficient" and weak.blocked, weak.as_dict()
    assert weak.score <= 40

    mid = assess(evidence=[{"source": "news"}], freshness_days=45,
                 disagreement=0.6, unresolved=2)
    assert mid.band in ("low", "insufficient"), mid.as_dict()
    assert any("分歧" in c for c in mid.caveats)

    assert tier_of("exchange") == 1.0 and tier_of("火星社") == _DEFAULT_TIER
    assert "不构成投资建议" in annotate("结论文本", strong)
    assert len(to_ui(strong)["radar"]) == 7
    print("self_assessment self-check ok:",
          f"strong={strong.score} weak={weak.score} mid={mid.score}")
