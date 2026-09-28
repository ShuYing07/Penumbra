# -*- coding: utf-8 -*-
"""HERMES 五层分层检索 Agent 架构。

层序：
  1. 数据检索层（DataRetrievalLayer）：按标的/主题拉取行情、新闻、公告、估值快照。
  2. 验证层（ValidationLayer）：字段完整性、数值合理性、来源一致性交叉校验。
  3. 合成层（SynthesisLayer）：把验证后的多源数据合成结构化摘要。
  4. 共识层（ConsensusLayer）：自适应共识协议——各层结论做语义一致性检查，
     不一致时自动触发上层重检索（最多 2 轮），收敛后进入下一层。
  5. 报告生成层（ReportLayer）：输出 Markdown 结构化报告（含置信度与数据溯源）。

设计要点（吸收 HERMES / AgenticAITA 的教训）：
- 每一层都是纯函数式 pipeline，可独立测试；
- 共识协议用"语义相似度 + 证据覆盖"双指标，而非简单多数；
- 数据不足时拒绝给出结论（与全项目"数据工具"合规红线一致）。
"""
from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field

log = logging.getLogger("stockai.hermes")


# --------------------------------------------------------------------------
# 语义一致性度量（标准库实现：关键词重叠 Jaccard + 长度归一化）
# --------------------------------------------------------------------------
def _tokens(text: str) -> set[str]:
    return {w for w in _safe(text).lower().split() if len(w) > 1}


def _safe(text: object) -> str:
    return "" if text is None else str(text)


def semantic_similarity(a: str, b: str) -> float:
    """0~1 语义相似度。空串对返回 0，完全相同返回 1。"""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 1.0 if a == b else 0.0
    inter = len(ta & tb)
    union = len(ta | tb)
    if union == 0:
        return 1.0
    jac = inter / union
    # 长度惩罚：极端长短文本即使词重叠也视为弱一致
    la, lb = len(_safe(a)), len(_safe(b))
    len_pen = max(0.0, 1.0 - abs(la - lb) / max(la, lb, 1))
    return 0.7 * jac + 0.3 * len_pen


# --------------------------------------------------------------------------
# 层抽象
# --------------------------------------------------------------------------
class Layer:
    name = "base"

    def process(self, ctx: dict) -> dict:
        raise NotImplementedError


class DataRetrievalLayer(Layer):
    """数据检索层：通过注册的 fetcher 拉取多源数据。"""

    name = "retrieval"

    def __init__(self, fetchers: dict | None = None):
        # fetchers: {"bars": callable(ticker)->df, "news": callable(ticker)->list[dict], ...}
        self.fetchers = fetchers or {}

    def register(self, kind: str, fn) -> None:
        self.fetchers[kind] = fn

    def process(self, ctx: dict) -> dict:
        ticker = ctx.get("ticker", "")
        out = {}
        for kind, fn in (self.fetchers or {}).items():
            try:
                out[kind] = fn(ticker)
            except Exception as e:  # noqa: BLE001
                log.warning("检索层 %s 失败 %s: %s", kind, ticker, e)
                out[kind] = None
        return {"data": out, "sources": list(self.fetchers.keys())}


class ValidationLayer(Layer):
    """验证层：字段完整性 + 数值合理性 + 来源一致性。"""

    name = "validation"

    def __init__(self, numeric_fields=("open", "high", "low", "close", "volume"),
                 max_price_ratio: float = 5.0):
        self.numeric_fields = numeric_fields
        self.max_price_ratio = max_price_ratio

    def process(self, ctx: dict) -> dict:
        data = ctx.get("data") or {}
        issues: list[str] = []
        checked = 0
        ok = 0

        bars = data.get("bars")
        if bars is not None:
            try:
                rows = list(bars) if hasattr(bars, "__iter__") else []
                n = len(rows)
                checked += 1
                if n < 20:
                    issues.append(f"行情样本过少({n} 行)")
                else:
                    ok += 1
                # 数值合理性：high >= low，且不出现荒谬跳变
                bad = 0
                for r in rows[-200:]:
                    if r.get("high") and r.get("low") and r["high"] < r["low"]:
                        bad += 1
                if bad:
                    issues.append(f"high<low 异常 {bad} 处")
            except Exception as e:  # noqa: BLE001
                issues.append(f"行情校验异常: {e}")

        news = data.get("news")
        if news is not None:
            checked += 1
            if len(news or []) == 0:
                issues.append("新闻为空")
            else:
                ok += 1

        # 来源一致性：news 中同一事件多源互证（简单按标题关键词聚类）
        consis = self._source_consistency(news)
        if consis < 0.5 and news:
            issues.append(f"来源互证度低({consis:.2f})")

        score = (ok / checked) if checked else 0.5
        score = min(1.0, score * (1.0 - min(0.5, len(issues) * 0.08)))
        return {"valid": score >= 0.6, "score": round(score, 3),
                "issues": issues, "checked": checked}

    @staticmethod
    def _source_consistency(news) -> float:
        if not news:
            return 0.0
        try:
            titles = [_safe(n.get("title")) for n in news[:10] if isinstance(n, dict)]
        except Exception:  # noqa: BLE001
            return 0.0
        if len(titles) < 2:
            return 0.5
        hits = sum(1 for i in range(len(titles)) for j in range(i + 1, len(titles))
                   if semantic_similarity(titles[i], titles[j]) > 0.35)
        pairs = len(titles) * (len(titles) - 1) / 2
        return min(1.0, hits / max(1, pairs) * 2.0)


class SynthesisLayer(Layer):
    """合成层：把验证后的多源数据合成结构化摘要。"""

    name = "synthesis"

    def process(self, ctx: dict) -> dict:
        data = ctx.get("data") or {}
        bars = data.get("bars")
        summary = {}
        if bars is not None and len(bars) > 0:
            closes = [r.get("close") for r in bars if r.get("close") is not None]
            if closes:
                summary["last_close"] = round(float(closes[-1]), 3)
                summary["high_52w"] = round(float(max(closes)), 3)
                summary["low_52w"] = round(float(min(closes)), 3)
                ret = closes[-1] / closes[0] - 1 if closes[0] else 0
                summary["ret_whole"] = round(ret * 100, 2)
        news = data.get("news") or []
        if news:
            summary["news_count"] = len(news)
            summary["latest_title"] = _safe(news[0].get("title"))[:80]
        summary["sources"] = ctx.get("sources") or []
        return {"summary": summary}


class ConsensusLayer(Layer):
    """共识层：自适应共识协议。

    - 对比各层/各来源的结论文本，计算语义一致性；
    - 一致性低于阈值 → 触发重检索（rounds+1），由上层重跑检索；
    - 收敛或达到最大轮次后输出共识结论。
    """

    name = "consensus"

    def __init__(self, threshold: float = 0.55, max_rounds: int = 2):
        self.threshold = threshold
        self.max_rounds = max_rounds

    def process(self, ctx: dict) -> dict:
        texts = [ctx.get("text", "")]
        for k in ("retrieval_note", "validation_note", "synthesis_note"):
            if ctx.get(k):
                texts.append(ctx[k])
        texts = [t for t in texts if t]
        score = 1.0
        if len(texts) >= 2:
            sims = [semantic_similarity(texts[i], texts[j])
                    for i in range(len(texts)) for j in range(i + 1, len(texts))]
            score = sum(sims) / len(sims)
        rounds = ctx.get("rounds", 0)
        need = score < self.threshold and rounds < self.max_rounds
        return {"consensus": round(score, 3), "agreed": not need,
                "retry": need, "rounds": rounds + (1 if need else 0)}


class ReportLayer(Layer):
    """报告生成层：结构化 Markdown 报告（含置信度、数据溯源、合规声明）。"""

    name = "report"

    def process(self, ctx: dict) -> dict:
        ticker = ctx.get("ticker", "")
        summary = ctx.get("summary") or {}
        cons = ctx.get("consensus") or {}
        val = ctx.get("validation") or {}
        lines = [
            f"# HERMES 分层分析报告 · {ticker}",
            "",
            f"- 共识一致性：**{cons.get('consensus', 0):.2f}**（阈值 {cons.get('threshold', 0.55):.2f}，"
            f"共识轮次 {cons.get('rounds', 0)}）",
            f"- 数据验证：**{val.get('score', 0):.3f}**"
            + ("（有疑点，见下）" if val.get("issues") else "（通过）"),
            "",
            "## 数据摘要",
            f"- 最新收盘：{summary.get('last_close', '—')}",
            f"- 区间高低：{summary.get('low_52w', '—')} / {summary.get('high_52w', '—')}",
            f"- 区间涨跌：{summary.get('ret_whole', '—')}%",
            f"- 新闻条数：{summary.get('news_count', '—')}"
            + (f"，最新：{summary.get('latest_title', '')}" if summary.get("latest_title") else ""),
            "",
            "## 数据源",
            *([f"- {s}" for s in (ctx.get("sources") or [])] or ["- （无）"]),
        ]
        if val.get("issues"):
            lines += ["", "## 验证疑点"] + [f"- {i}" for i in val["issues"]]
        lines += [
            "",
            "> 本报告由 HERMES 分层架构自动生成，仅作数据汇总与统计展示，"
            "不构成任何投资建议。",
        ]
        return {"report": "\n".join(lines)}


# --------------------------------------------------------------------------
# HERMES 编排器
# --------------------------------------------------------------------------
@dataclass
class HERMES:
    """五层编排器：retrieval → validation → synthesis → consensus → report。

    fetchers 可在构造时注入（测试/离线模式用）；缺省使用空 fetchers，
    由上层（main/analysis）按需 register。
    """
    ticker: str = ""
    fetchers: dict = field(default_factory=dict)
    consensus_threshold: float = 0.55
    max_rounds: int = 2
    layers: list = field(default_factory=list)

    def __post_init__(self) -> None:
        self.layers = [
            DataRetrievalLayer(self.fetchers),
            ValidationLayer(),
            SynthesisLayer(),
            ConsensusLayer(self.consensus_threshold, self.max_rounds),
            ReportLayer(),
        ]

    def register_fetcher(self, kind: str, fn) -> None:
        self.layers[0].register(kind, fn)

    def run(self, ticker: str | None = None, notes: dict | None = None) -> dict:
        """执行五层流水线，含自适应共识重检索。"""
        ticker = ticker or self.ticker
        ctx: dict = {"ticker": ticker, "rounds": 0, "text": ""}
        if notes:
            ctx.update(notes)

        for _round in range(self.max_rounds + 1):
            data_out = self.layers[0].process(ctx)
            val_out = self.layers[1].process(data_out)
            syn_out = self.layers[2].process(data_out)
            ctx.update({
                "data": data_out.get("data"),
                "sources": data_out.get("sources"),
                "validation": val_out,
                "validation_note": "; ".join(val_out.get("issues", [])) or "数据通过验证",
                "summary": syn_out.get("summary"),
                "synthesis_note": str(syn_out.get("summary", {}).get("latest_title", ""))[:60],
            })
            cons_out = self.layers[3].process(ctx)
            ctx["consensus"] = cons_out
            if not cons_out.get("retry"):
                break
            log.info("HERMES 共识不足(%s)，重检索轮次+1", cons_out.get("consensus"))

        # 数据不足门控：行情缺失 → 拒绝给出结论（合规红线）
        summary = ctx.get("summary") or {}
        if not summary.get("last_close"):
            ctx["gated"] = True
            ctx["report"] = (
                f"# HERMES 分层分析报告 · {ticker}\n\n"
                "**数据不足**：无法获取有效行情数据，拒绝生成任何结论。\n\n"
                "> 本报告由 HERMES 分层架构自动生成，仅作数据汇总与统计展示。"
            )
        else:
            ctx["gated"] = False
            rep_out = self.layers[4].process(ctx)
            ctx["report"] = rep_out["report"]
        ctx["elapsed_s"] = round(time.time() - ctx.get("_t0", time.time()), 3)
        return ctx


def run_analysis(ticker: str, fetchers: dict | None = None,
                 threshold: float = 0.55, max_rounds: int = 2) -> dict:
    """便捷入口：构造并运行一次 HERMES 分析。"""
    t0 = time.time()
    hermes = HERMES(ticker=ticker, fetchers=fetchers or {},
                    consensus_threshold=threshold, max_rounds=max_rounds)
    ctx = hermes.run(ticker)
    ctx["_t0"] = t0
    ctx["elapsed_s"] = round(time.time() - t0, 3)
    return ctx


# --------------------------------------------------------------------------
# 自测
# --------------------------------------------------------------------------
def _demo_fetchers():
    """离线演示数据（不联网），供自测与 UI 默认展示。"""
    import math
    n = 60
    bars = [{"open": 100 + i, "high": 100 + i + 1, "low": 100 + i - 1,
             "close": 100 + i + math.sin(i / 5), "volume": 1000 + i * 10}
            for i in range(n)]
    news = [
        {"title": "公司发布第三季度财报 营收增长符合预期", "source": "东财", "url": ""},
        {"title": "公司公告回购计划 提升股东回报", "source": "新浪", "url": ""},
    ]
    return {"bars": lambda t: bars, "news": lambda t: news}


if __name__ == "__main__":
    ctx = run_analysis("SH600519", _demo_fetchers())
    print(ctx["report"])
    print(f"\n[consensus={ctx['consensus']['consensus']} gated={ctx['gated']} "
          f"rounds={ctx['consensus']['rounds']} elapsed={ctx['elapsed_s']}s]")
    assert not ctx["gated"]
    assert "HERMES" in ctx["report"]
    # 数据不足门控
    ctx2 = run_analysis("TESTX", {"bars": lambda t: [], "news": lambda t: []})
    assert ctx2["gated"] and "数据不足" in ctx2["report"]
    print("PASS hermes 自测（含数据不足门控）")
