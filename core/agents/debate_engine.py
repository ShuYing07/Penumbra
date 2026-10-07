# -*- coding: utf-8 -*-
"""Claim-level 结构化多空辩论引擎（模块二）。

为什么需要"结构化"：自由文本的多空辩论（各说 3-5 条理由）看起来热闹，
但无法审计——读者不知道每条论点依据什么数据、被反驳了没有、为什么还成立。
TradingAgents 的关键设计就是把辩论落到 **Claim（论点）+ Evidence（证据）+
Rebuttal（反驳）** 三元组上，让每一步都可追溯、可计分。

本实现的两条设计原则：
1. **离线确定性优先**：论点生成与反驳全部基于分析师已产出的结构化信号
   （stance/confidence/key_points/risks），不依赖 LLM 也能跑出完整辩论，
   因此可单测、可复现；有 LLM 时仅做"措辞增强"，不改变结构与判定。
2. **无证据不立论**：一条 Claim 若没有可引用的证据，判定为 invalid，
   不计入计分——这条硬约束直接消灭"空口断言"类幻觉。

合规：辩论产出的是**研究性多空论据对照**，不含买卖建议/目标价/收益承诺。
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

log = logging.getLogger("stockai.agents.debate")

Side = Literal["bull", "bear"]
RebutMethod = Literal["data", "logic", "timeliness", "magnitude", "scope"]

# 论题标签：用于把"对立证据"配对起来（无 LLM 也能做数据型反驳）
TOPIC_TAGS: Dict[str, List[str]] = {
    "估值": ["估值", "市盈率", "市净率", "pe", "pb", "ps", "贵", "便宜", "折价", "溢价"],
    "业绩": ["营收", "净利", "业绩", "增长", "毛利", "利润", "eps", "roe", "预增", "预减"],
    "技术": ["均线", "macd", "rsi", "kdj", "突破", "趋势", "支撑", "压力", "金叉", "死叉",
             "超买", "超卖", "背离"],
    "资金": ["资金", "北向", "主力", "成交", "量能", "换手", "流入", "流出", "持仓"],
    "情绪": ["情绪", "舆情", "热度", "讨论", "搜索", "散户", "人气"],
    "宏观": ["宏观", "政策", "利率", "通胀", "汇率", "货币", "财政", "行业周期"],
    "风险": ["风险", "回撤", "波动", "负债", "减持", "质押", "诉讼", "商誉", "监管"],
}

_BULL_WORDS = ("看多", "偏多", "上涨", "走强", "利好", "改善", "提升", "增长")
_BEAR_WORDS = ("看空", "偏空", "下跌", "走弱", "利空", "恶化", "下滑", "承压")


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------
class Evidence(BaseModel):
    """一条论点所引用的证据：来自哪个分析师/数据源、具体是什么、时点。"""
    source: str = Field(description="证据来源：technical/fundamental/... 或数据字段名")
    detail: str = Field(description="证据内容（原始信号文本或数值描述）")
    as_of: str = Field(default="", description="数据时点（可空）")
    confidence: int = Field(default=50, ge=1, le=99, description="该证据来源的置信度")


class Claim(BaseModel):
    """一条结构化论点。"""
    id: str
    side: Side
    text: str
    evidence: List[Evidence] = Field(default_factory=list)
    confidence: int = Field(default=50, ge=1, le=99)
    topics: List[str] = Field(default_factory=list)
    round_no: int = 1
    valid: bool = True          # 无证据 → False（不立论）
    invalid_reason: str = ""

    def evidence_ok(self) -> bool:
        return bool(self.evidence)


class Rebuttal(BaseModel):
    """针对某条 Claim 的反驳。"""
    claim_id: str
    by: Side                       # 反驳方
    method: RebutMethod
    text: str
    evidence: List[Evidence] = Field(default_factory=list)
    strength: float = Field(default=0.5, ge=0.0, le=1.0, description="反驳力度")
    effective: bool = False        # strength >= 阈值 且 有证据 → 有效反驳


class DebateRound(BaseModel):
    round_no: int
    claims: List[Claim] = Field(default_factory=list)
    rebuttals: List[Rebuttal] = Field(default_factory=list)


class DebateTranscript(BaseModel):
    """完整辩论记录（可序列化、可回放、可在 UI 展示）。"""
    ticker: str = ""
    rounds: List[DebateRound] = Field(default_factory=list)
    bull_score: float = 0.0
    bear_score: float = 0.0
    unresolved: List[str] = Field(default_factory=list, description="未被有效反驳的核心分歧")
    consensus: str = ""
    caveats: List[str] = Field(default_factory=list)
    mode: str = "rule"             # rule / llm_enhanced

    @property
    def winner(self) -> str:
        if abs(self.bull_score - self.bear_score) < 0.05:
            return "多空均衡"
        return "多方占优" if self.bull_score > self.bear_score else "空方占优"


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------
def _cid(side: str, text: str, round_no: int) -> str:
    h = hashlib.md5(f"{side}|{round_no}|{text}".encode("utf-8")).hexdigest()[:8]
    return f"{side[:1]}{round_no}-{h}"


def tag_of(text: str) -> List[str]:
    """从文本里抽取论题标签（用于配对对立证据）。"""
    low = (text or "").lower()
    return [tag for tag, kws in TOPIC_TAGS.items()
            if any(k in low for k in kws)] or ["综合"]


def _sig_of(state: Dict[str, Any], key: str) -> Dict[str, Any]:
    sig = (state.get("signals") or {}).get(key) or {}
    return sig if isinstance(sig, dict) else {}


def _stance_of(sig: Dict[str, Any]) -> str:
    return str(sig.get("stance") or "中性")


def _is_bullish(sig: Dict[str, Any]) -> bool:
    s = _stance_of(sig)
    return s == "看多" or (s == "中性" and any(w in str(sig.get("view", "")) for w in _BULL_WORDS))


def _is_bearish(sig: Dict[str, Any]) -> bool:
    s = _stance_of(sig)
    return s == "看空" or (s == "中性" and any(w in str(sig.get("view", "")) for w in _BEAR_WORDS))


def _ev(sig: Dict[str, Any], key: str, detail: str) -> Evidence:
    return Evidence(source=key, detail=detail,
                    confidence=int(sig.get("confidence", 50) or 50))


# ---------------------------------------------------------------------------
# 论点生成
# ---------------------------------------------------------------------------
def build_claims(state: Dict[str, Any], side: Side, max_claims: int = 3,
                 round_no: int = 1) -> List[Claim]:
    """从分析师信号里提炼结构化论点（每条必须带证据）。

    - 多方论点：看多分析师的 key_points；
    - 空方论点：看空分析师的 key_points + 所有分析师的 risks（风险天然是空方论据）。
    """
    signals: Dict[str, Any] = state.get("signals") or {}
    out: List[Claim] = []

    def _add(text: str, key: str, sig: Dict[str, Any]) -> None:
        out.append(Claim(id=_cid(side, text, round_no), side=side, text=text,
                         evidence=[_ev(sig, key, str(sig.get("view") or text))],
                         confidence=int(sig.get("confidence", 50) or 50),
                         topics=tag_of(text), round_no=round_no))

    for key, sig in (signals.items() if isinstance(signals, dict) else []):
        if not isinstance(sig, dict):
            continue
        bullish, bearish = _is_bullish(sig), _is_bearish(sig)
        if side == "bull" and not bullish:
            continue
        if side == "bear" and not bearish:
            continue
        points = [p for p in (sig.get("key_points") or []) if str(p).strip()]
        if side == "bear":
            # 风险提示天然是空方论据（"看多但短线超买"是最有价值的交叉质询素材）
            points += [r for r in (sig.get("risks") or []) if str(r).strip()]
        for p in points[:2]:                      # 同一分析师最多贡献 2 条，避免刷屏
            _add(str(p).strip(), key, sig)

    if side == "bear":
        # 补充：看多/中性分析师**自我披露的风险**，是最有力的交叉质询素材
        for key, sig in (signals.items() if isinstance(signals, dict) else []):
            if not isinstance(sig, dict) or _is_bearish(sig):
                continue
            for r in (sig.get("risks") or []):
                text = str(r).strip()
                if text:
                    _add(text, key, sig)
    # 按置信度排序取前 N；证据缺失的论点标记 invalid（不立论）
    out.sort(key=lambda c: c.confidence, reverse=True)
    claims = out[:max_claims]
    for c in claims:
        if not c.evidence_ok():
            c.valid = False
            c.invalid_reason = "无可引用证据，按无证据不立论原则剔除"
    return [c for c in claims if c.valid]


# ---------------------------------------------------------------------------
# 反驳生成
# ---------------------------------------------------------------------------
def rebut(claim: Claim, state: Dict[str, Any], by: Side,
          strength_threshold: float = 0.5) -> Rebuttal:
    """对一条论点生成结构化反驳（四类方法，全部基于已有信号，不编造）。"""
    signals: Dict[str, Any] = state.get("signals") or {}
    topics = set(claim.topics) - {"综合"}     # "综合"不是真论题，不参与匹配

    # ⓪ 论点自身置信度过低 → 先判"证据强度不足"（最强、最省事的驳回）
    if claim.confidence < 45:
        return Rebuttal(
            claim_id=claim.id, by=by, method="magnitude",
            text=f"该论点来源置信度仅 {claim.confidence}%，证据强度不足，不足以单独支撑结论",
            evidence=[], strength=0.55, effective=True)

    # ① 数据型反驳：找到对立立场、且**论题标签相交**的分析师证据
    counter: Optional[Evidence] = None
    counter_src = ""
    loose: Optional[Evidence] = None          # 无论题相交时的跨维度反证
    loose_src = ""
    for key, sig in (signals.items() if isinstance(signals, dict) else []):
        if not isinstance(sig, dict):
            continue
        opposite = _is_bearish(sig) if by == "bear" else _is_bullish(sig)
        if not opposite:
            continue
        pool = list(sig.get("key_points") or []) + [str(sig.get("view") or "")]
        for p in pool:
            if not str(p).strip():
                continue
            if topics & (set(tag_of(str(p))) - {"综合"}):
                counter, counter_src = _ev(sig, key, str(p).strip()), key
                break
            if loose is None and not topics:
                loose, loose_src = _ev(sig, key, str(p).strip()), key
        if counter:
            break

    if counter:
        rel = int(counter.confidence)
        strength = min(0.9, 0.45 + rel / 200)
        return Rebuttal(
            claim_id=claim.id, by=by, method="data",
            text=f"[{counter_src}] 给出相反证据：{counter.detail}",
            evidence=[counter], strength=round(strength, 2),
            effective=strength >= strength_threshold)

    # ② 跨维度反证（无论题相交时）：力度低于同论题反证，默认不构成有效反驳
    if loose is not None:
        return Rebuttal(
            claim_id=claim.id, by=by, method="scope",
            text=(f"[{loose_src}] 从另一维度给出不同信号：{loose.detail}"
                  "——跨维度证据不能直接证伪本论点，仅提示需综合考量"),
            evidence=[loose], strength=0.45, effective=False)

    # ③ 时效/幅度/范围型反驳（基于论点自身属性，无需外部数据）
    if claim.confidence < 55:
        return Rebuttal(
            claim_id=claim.id, by=by, method="magnitude",
            text=f"该论点来源置信度仅 {claim.confidence}%，证据强度不足，不足以单独支撑结论",
            evidence=[], strength=0.55, effective=True)
    if not any(ch.isdigit() for ch in claim.text):
        return Rebuttal(
            claim_id=claim.id, by=by, method="scope",
            text="该论点缺少可验证的量化依据（无具体数值/区间/时点），难以证伪也难以证实",
            evidence=[], strength=0.5, effective=True)
    return Rebuttal(
        claim_id=claim.id, by=by, method="logic",
        text="未见同论题下的直接反证；该论点在当前证据集内暂时成立，但需后续数据验证",
        evidence=[], strength=0.25, effective=False)


# ---------------------------------------------------------------------------
# 辩论流程
# ---------------------------------------------------------------------------
def run_claim_debate(state: Dict[str, Any], rounds: int = 2,
                     max_claims: int = 3, runner=None,
                     strength_threshold: float = 0.5) -> DebateTranscript:
    """运行 Claim-level 多空辩论。

    流程：第 1 轮 多方立论(≤3) → 空方逐条反驳；空方立论(≤3) → 多方逐条反驳；
    第 2 轮 对"未被有效反驳"的论点做二次质证（换一个角度：时效/幅度）。
    """
    rounds = max(1, min(int(rounds), 3))
    ticker = str(state.get("ticker") or "")
    transcript = DebateTranscript(ticker=ticker, mode="rule")

    bull_claims = build_claims(state, "bull", max_claims, round_no=1)
    bear_claims = build_claims(state, "bear", max_claims, round_no=1)

    r1 = DebateRound(round_no=1, claims=bull_claims + bear_claims)
    for c in bull_claims:
        r1.rebuttals.append(rebut(c, state, "bear", strength_threshold))
    for c in bear_claims:
        r1.rebuttals.append(rebut(c, state, "bull", strength_threshold))
    transcript.rounds.append(r1)

    # 第 2 轮：对仍未被有效反驳的核心论点做二次质证
    rb_index = {r.claim_id: r for r in r1.rebuttals}
    survivors = [c for c in bull_claims + bear_claims
                 if not rb_index.get(c.id) or not rb_index[c.id].effective]
    if rounds >= 2 and survivors:
        r2 = DebateRound(round_no=2)
        for c in survivors:
            again = rebut(c, state, "bear" if c.side == "bull" else "bull",
                          strength_threshold)
            if again.method == "logic":
                # 第一轮"未见反证"的论点，第二轮换个角度：时效性（而非自相矛盾地再反驳一次）
                again.method = "timeliness"
                again.text = (f"该论点在当前证据集内无直接反证，但其结论依赖的历史窗口"
                              f"可能已失效（信号基于截至目前的样本），需以最新数据复核")
                again.strength = 0.5
            else:
                again.method = "timeliness"
                again.text = f"（二次质证·时效性）{again.text}；且该证据存在时滞，需复核最新值"
            again.strength = round(min(0.8, again.strength + 0.1), 2)
            again.effective = again.strength >= strength_threshold
            r2.claims.append(c)
            r2.rebuttals.append(again)
        transcript.rounds.append(r2)

    _score(transcript)
    return transcript


def _score(t: DebateTranscript) -> None:
    """按"论点置信度 × (1 - 反驳力度)"计分，并给出未解分歧与共识。"""
    bull, bear = 0.0, 0.0
    worst: Dict[str, Rebuttal] = {}
    for r in t.rounds:
        rb = {x.claim_id: x for x in r.rebuttals}
        for c in r.claims:
            hit = rb.get(c.id)
            eff = hit.strength if (hit and hit.effective) else 0.0
            value = (c.confidence / 100.0) * (1.0 - eff)
            if c.side == "bull":
                bull += value
            else:
                bear += value
            if hit and not hit.effective:
                prev = worst.get(c.id)
                if prev is None or hit.strength > prev.strength:
                    worst[c.id] = hit
    total = bull + bear
    if total > 0:
        t.bull_score = round(bull / total, 3)
        t.bear_score = round(bear / total, 3)
    else:
        t.bull_score = t.bear_score = 0.5

    t.unresolved = [f"{rb.text}" for rb in worst.values()][:5]
    if not t.rounds or not any(r.claims for r in t.rounds):
        t.consensus = "分析师信号不足，未形成有效多空论点（数据不足，不做判断）"
        t.caveats = ["无有效论点：可能因数据缺失或所有分析师均为中性"]
    else:
        gap = abs(t.bull_score - t.bear_score)
        t.consensus = (f"多空论据对照：{t.winner}"
                       f"（多方 {t.bull_score:.0%} / 空方 {t.bear_score:.0%}）"
                       + ("，分歧接近，建议等待更明确信号" if gap < 0.1 else ""))
        t.caveats = ["辩论结论为研究性论据对照，不构成投资建议",
                     "计分基于程序化信号，非预测正确率"]
    t.caveats.append("无证据不立论：缺少来源的论点已剔除")


def to_ui(t: DebateTranscript) -> Dict[str, Any]:
    """给 UI 展示用的扁平结构。"""
    return {
        "ticker": t.ticker,
        "winner": t.winner,
        "bull_score": t.bull_score,
        "bear_score": t.bear_score,
        "consensus": t.consensus,
        "unresolved": t.unresolved,
        "caveats": t.caveats,
        "rounds": [
            {
                "round_no": r.round_no,
                "claims": [{"id": c.id, "side": c.side, "text": c.text,
                            "confidence": c.confidence, "topics": c.topics,
                            "evidence": [e.model_dump() for e in c.evidence]}
                           for c in r.claims],
                "rebuttals": [{"claim_id": x.claim_id, "by": x.by, "method": x.method,
                               "text": x.text, "strength": x.strength,
                               "effective": x.effective,
                               "evidence": [e.model_dump() for e in x.evidence]}
                              for x in r.rebuttals],
            }
            for r in t.rounds
        ],
    }
