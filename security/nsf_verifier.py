# -*- coding: utf-8 -*-
"""神经符号约束验证器（VA-NSF 工程实现）（2026-10 翻新 · 模块一/六）。

参考 Nature Sci Rep 2026《Verifier-Actor Neuro-Symbolic Framework》：
把「自然语言理解」与「形式化约束执行」解耦——神经层（LLM）负责生成，
符号层（本模块）用**确定性完整性约束**对输出做形式化验证：

- 通过 → 签发**批准证书**（含约束通过清单 + 内容指纹，可审计）；
- 违反 → 输出**结构化违规报告**（约束 id / 严重度 / 定位 / 定向修复建议），
  驱动定点修复而非整段重写。

论文用 ASP 完整性约束求解；本项目以「声明式约束集 + 确定性求值器」实现
等价能力（零新依赖、可单测、毫秒级），并额外支持**流式增量校验**——
在 LLM 生成过程中逐块检查，把合规从「事后刹车」升级为「实时护栏」。

四类硬约束：
- H（硬性，hard）：违反即拦截（荐股/目标价/收益承诺/内幕敏感词/未来确定性断言）
- S（结构，structure）：输出必须有结论/依据/风险提示与免责声明
- N（数值，numeric）：数值必须可溯源到工具结果（防幻觉），指标名须在白名单
- B（业务，business）：仓位上限、杠杆、单标的集中度等硬性业务规则
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ---------------------------------------------------------------------------
# 词表与白名单
# ---------------------------------------------------------------------------

# 指令性交易动词（与标的共现 → 视为荐股）
_TRADE_VERBS = ("买入", "卖出", "加仓", "减仓", "清仓", "建仓", "补仓", "抄底",
                "追高", "梭哈", "满仓", "重仓买入", "赶紧买", "赶紧卖",
                "buy", "sell", "long", "short")
# 收益承诺
_PROMISE_WORDS = ("保证收益", "稳赚", "必赚", "包赚", "无风险", "百分百",
                  "一定涨", "必然上涨", "翻倍", "躺赚", "稳赢", "保本保息")
# 目标价表达
_TARGET_PRICE_RE = re.compile(
    r"(目标价|目标位|看到|涨到|跌到|上看|下看)[^。；\n]{0,12}?\d+(\.\d+)?\s*(元|块|美元|港元|港币)?")
# 内幕/操纵敏感词
_SENSITIVE_WORDS = ("内幕", "内部消息", "庄家", "拉升", "坐庄", "老鼠仓",
                    "操盘", "割韭菜", "涨停敢死队")
# 未来确定性断言（违反「不确定表述」约束）
_FUTURE_ASSERT_RE = re.compile(r"(必将|一定会|必然|毫无疑问|100%\s*会)")
# 指标白名单（防自造指标幻觉）
_METRIC_WHITELIST = (
    "RSI", "MACD", "DIF", "DEA", "MA", "SMA", "EMA", "BOLL", "KDJ", "ATR",
    "PE", "PB", "PS", "ROE", "ROIC", "ROA", "EPS", "毛利率", "净利率",
    "营收", "净利润", "现金流", "资产负债率", "换手率", "成交额", "成交量",
    "涨跌幅", "收盘价", "开盘价", "最高价", "最低价", "年化", "最大回撤",
    "夏普", "波动率", "VaR", "贝塔", "Beta", "市值", "股息率", "分红",
    "毛利率", "净现比", "存货周转", "应收账款",
)
# 自造指标模式（形如 XX指标/自定义指标名 + 数字）
_CUSTOM_METRIC_RE = re.compile(r"([\u4e00-\u9fa5A-Za-z]{2,8}(指标|系数|指数|评分|得分))\s*[:：]?\s*-?\d")

_REQUIRED_DISCLAIMER = ("不构成投资建议", "不构成任何投资建议", "仅供研究",
                        "非投资建议", "不构成建议")


# ---------------------------------------------------------------------------
# 约束定义
# ---------------------------------------------------------------------------

@dataclass
class Constraint:
    id: str
    category: str          # H / S / N / B
    severity: str          # critical / high / medium
    description: str
    check: Callable[[str, Dict[str, Any]], bool]   # True=满足约束
    repair: str


@dataclass
class Violation:
    id: str
    category: str
    severity: str
    message: str
    repair: str
    location: str = ""


@dataclass
class Verdict:
    approved: bool
    violations: List[Violation] = field(default_factory=list)
    passed: List[str] = field(default_factory=list)
    fingerprint: str = ""
    score: int = 100
    certificate: Dict[str, Any] = field(default_factory=dict)

    def report(self) -> str:
        """人类可读的违规报告。"""
        if self.approved:
            return (f"✅ 批准证书 fp={self.fingerprint[:12]} · "
                    f"通过 {len(self.passed)} 条约束 · 评分 {self.score}/100")
        lines = [f"❌ 违规报告（{len(self.violations)} 项）· 评分 {self.score}/100"]
        for v in self.violations:
            lines.append(f"  [{v.severity}/{v.category}] {v.id} {v.message}"
                         + (f" @{v.location}" if v.location else ""))
            lines.append(f"    修复：{v.repair}")
        return "\n".join(lines)


def _has_ticker(text: str) -> bool:
    return bool(re.search(r"\b(?:SH|SZ|BJ|HK)?\d{6}\b|\b[A-Z]{1,5}\b|"
                          r"\d{4}\.HK", text))


def _numbers(text: str) -> List[float]:
    """抽取「独立数值」：跳过带字母前缀的 token（RSI14 / MA20 / SH600519 /
    PE30 属于指标名或股票代码，不是待溯源数值）。"""
    out: List[float] = []
    for tok in re.findall(r"[A-Za-z]*-?\d+(?:\.\d+)?", text):
        m = re.match(r"^([A-Za-z]*)(-?\d+(?:\.\d+)?)$", tok)
        if not m or m.group(1):      # 有字母前缀 → 指标名/代码，跳过
            continue
        out.append(float(m.group(2)))
    return out


def _evidence_numbers(ctx: Dict[str, Any]) -> List[float]:
    """从上下文（工具结果）中抽取可溯源数值。"""
    out: List[float] = []
    ev = ctx.get("evidence") or {}

    def walk(o: Any):
        if isinstance(o, (int, float)):
            out.append(float(o))
        elif isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, (list, tuple)):
            for v in o:
                walk(v)

    walk(ev)
    return out


# ---- H 类：硬性合规 ----
def _c_no_recommendation(text: str, ctx: Dict[str, Any]) -> bool:
    for v in _TRADE_VERBS:
        if v.lower() in text.lower() and _has_ticker(text):
            # 排除「不构成投资建议」等否定语境中的动词
            for neg in ("不建议", "不构成", "不应", "避免"):
                if neg in text:
                    return True
            return False
    return True


def _c_no_target_price(text: str, ctx: Dict[str, Any]) -> bool:
    return _TARGET_PRICE_RE.search(text) is None


def _c_no_promise(text: str, ctx: Dict[str, Any]) -> bool:
    return not any(w in text for w in _PROMISE_WORDS)


def _c_no_sensitive(text: str, ctx: Dict[str, Any]) -> bool:
    return not any(w in text for w in _SENSITIVE_WORDS)


def _c_no_future_assert(text: str, ctx: Dict[str, Any]) -> bool:
    return _FUTURE_ASSERT_RE.search(text) is None


# ---- S 类：结构 ----
def _c_has_disclaimer(text: str, ctx: Dict[str, Any]) -> bool:
    return any(w in text for w in _REQUIRED_DISCLAIMER)


def _c_has_risk_note(text: str, ctx: Dict[str, Any]) -> bool:
    return any(w in text for w in ("风险", "回撤", "波动", "不确定性"))


def _c_min_length(text: str, ctx: Dict[str, Any]) -> bool:
    return len(text.strip()) >= int(ctx.get("min_length", 20))


# ---- N 类：数值可溯源 / 指标白名单 ----
def _c_metric_whitelist(text: str, ctx: Dict[str, Any]) -> bool:
    """出现的指标名须在白名单内（允许白名单作为子串匹配）。"""
    for m in _CUSTOM_METRIC_RE.finditer(text):
        name = m.group(1)
        base = name.replace("指标", "").replace("系数", "").replace(
            "指数", "").replace("评分", "").replace("得分", "")
        if base and not any(w.lower() in name.lower() or w in name
                            for w in _METRIC_WHITELIST):
            return False
    return True


def _c_numeric_traceable(text: str, ctx: Dict[str, Any]) -> bool:
    """数值可溯源：给定 evidence 时，正文关键数值须能在证据中找到（容差 5%）。

    未给 evidence（无工具调用）时跳过——避免对纯叙述文本误伤。
    """
    ev_nums = _evidence_numbers(ctx)
    if not ev_nums:
        return True
    tol = float(ctx.get("numeric_tolerance", 0.05))
    unmatched: List[float] = []
    for n in _numbers(text):
        if abs(n) < 1e-9:
            continue
        if any(abs(n - e) <= max(abs(e) * tol, 1e-6) for e in ev_nums):
            continue
        unmatched.append(n)
    # 默认只容忍 1 个无来源数值（年份/序号等），超出即判不可溯源
    return len(unmatched) <= int(ctx.get("max_unmatched_numbers", 1))


# ---- B 类：业务硬规则 ----
def _c_position_limit(text: str, ctx: Dict[str, Any]) -> bool:
    """单标的仓位不得超过上限（默认 20%）。"""
    cap = float(ctx.get("max_position_pct", 20.0))
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*%?\s*(?:仓位|持仓|配置比例)", text):
        if float(m.group(1)) > cap:
            return False
    return True


def _c_no_leverage_advice(text: str, ctx: Dict[str, Any]) -> bool:
    return not re.search(r"(加杠杆|配资|融资融券\s*买入|满仓\s*杠杆)", text)


CONSTRAINTS: List[Constraint] = [
    Constraint("H01", "H", "critical", "不得给出买卖建议（荐股）",
               _c_no_recommendation,
               "删除指令性动词，改为客观描述数据（如「RSI 为 72」而非「建议买入」）"),
    Constraint("H02", "H", "critical", "不得给出目标价",
               _c_no_target_price,
               "删除目标价/目标位表述，改为区间与条件描述"),
    Constraint("H03", "H", "critical", "不得承诺收益",
               _c_no_promise,
               "删除收益承诺词，补充「历史表现不代表未来」"),
    Constraint("H04", "H", "high", "不得涉及内幕/操纵敏感词",
               _c_no_sensitive, "删除敏感词，仅引用公开信息"),
    Constraint("H05", "H", "high", "不得对未来做确定性断言",
               _c_no_future_assert, "改为概率/条件表述（「若…则可能…」）"),
    Constraint("S01", "S", "high", "必须包含免责声明",
               _c_has_disclaimer, "文末补充「本文不构成投资建议，仅供研究」"),
    Constraint("S02", "S", "medium", "必须包含风险提示",
               _c_has_risk_note, "补充风险提示段落（波动/回撤/不确定性）"),
    Constraint("S03", "S", "low", "内容长度满足下限",
               _c_min_length, "补充分析内容"),
    Constraint("N01", "N", "high", "指标名须在白名单内（防自造指标）",
               _c_metric_whitelist, "改用标准指标名或说明计算口径"),
    Constraint("N02", "N", "high", "数值须可溯源到工具结果",
               _c_numeric_traceable, "为数值补充来源，或删除无来源数值"),
    Constraint("B01", "B", "high", "单标的仓位不得超过上限",
               _c_position_limit, f"将仓位降到上限以内"),
    Constraint("B02", "B", "high", "不得建议加杠杆/配资",
               _c_no_leverage_advice, "删除杠杆建议，提示杠杆风险"),
]

_SEVERITY_PENALTY = {"critical": 40, "high": 20, "medium": 8, "low": 3}
_BLOCKING = {"critical", "high"}


# ---------------------------------------------------------------------------
# 符号验证器
# ---------------------------------------------------------------------------

def verify(text: str, ctx: Optional[Dict[str, Any]] = None,
           constraints: Optional[List[Constraint]] = None) -> Verdict:
    """对输出文本执行全部约束；返回批准证书或结构化违规报告。"""
    ctx = dict(ctx or {})
    cons = constraints or CONSTRAINTS
    passed, violations = [], []
    for c in cons:
        try:
            ok = c.check(text, ctx)
        except Exception as e:  # noqa: BLE001  约束求值失败按「未通过」保守处理
            violations.append(Violation(c.id, c.category, c.severity,
                                        f"约束求值异常：{e}", c.repair))
            continue
        if ok:
            passed.append(c.id)
        else:
            violations.append(Violation(
                c.id, c.category, c.severity, c.description, c.repair,
                location=_locate(text, c)))
    score = max(0, 100 - sum(_SEVERITY_PENALTY.get(v.severity, 5)
                             for v in violations))
    approved = not any(v.severity in _BLOCKING for v in violations)
    fp = hashlib.sha256(text.encode("utf-8")).hexdigest()
    cert = {"passed": passed, "fingerprint": fp,
            "ts": round(time.time(), 3),
            "constraint_count": len(cons)}
    return Verdict(approved, violations, passed, fp, score,
                   cert if approved else {})


def _locate(text: str, c: Constraint) -> str:
    """给出违规定位（片段），便于定向修复。"""
    probes = {
        "H01": _TRADE_VERBS, "H02": ("目标价", "目标位", "看到", "上看"),
        "H03": _PROMISE_WORDS, "H04": _SENSITIVE_WORDS,
        "H05": ("必将", "一定会", "必然", "毫无疑问"),
        "S01": _REQUIRED_DISCLAIMER, "S02": ("风险", "回撤"),
        "B01": ("仓位", "持仓"), "B02": ("杠杆", "配资"),
    }.get(c.id, ())
    for p in probes:
        i = text.find(p)
        if i >= 0:
            return text[max(0, i - 8): i + 18].replace("\n", " ")
    return ""


def check_incremental(accumulated: str, ctx: Optional[Dict[str, Any]] = None
                      ) -> List[Violation]:
    """流式护栏：对「已生成的部分文本」增量校验。

    只报 critical 级违规（H01-H03 等），用于生成过程中提前中断/改写，
    避免生成完整后再整段推翻（延迟与 token 双降）。
    """
    ctx = dict(ctx or {})
    out: List[Violation] = []
    for c in CONSTRAINTS:
        if c.category == "H" and c.severity == "critical":
            try:
                if not c.check(accumulated, ctx):
                    out.append(Violation(c.id, c.category, c.severity,
                                         c.description, c.repair,
                                         _locate(accumulated, c)))
            except Exception:  # noqa: BLE001
                continue
    return out


def guard_stream(chunks, ctx: Optional[Dict[str, Any]] = None,
                 on_violation: Optional[Callable[[List[Violation], str], None]] = None
                 ) -> Tuple[str, List[Violation]]:
    """逐块消费 LLM 流：命中 critical 约束立即回调（可中断生成）。

    返回 (已接受文本, 违规列表)。调用方可在 on_violation 中中止流。
    """
    ctx = dict(ctx or {})
    buf, hits = "", []
    seen: set[str] = set()
    for chunk in chunks:
        buf += chunk
        for v in check_incremental(buf, ctx):
            if v.id not in seen:
                seen.add(v.id)
                hits.append(v)
        if hits and on_violation:
            on_violation(hits, buf)
    return buf, hits


def load_constraints(path: str) -> List[Constraint]:
    """从 JSON 加载自定义约束（仅支持内置 check 的 id 引用）。"""
    with open(path, encoding="utf-8") as f:
        spec = json.load(f)
    by_id = {c.id: c for c in CONSTRAINTS}
    out = []
    for item in spec:
        base = by_id.get(item.get("id", ""))
        if not base:
            continue
        out.append(Constraint(
            base.id, base.category,
            item.get("severity", base.severity),
            item.get("description", base.description),
            base.check, item.get("repair", base.repair)))
    return out or CONSTRAINTS


if __name__ == "__main__":
    # 1) 违规样本：荐股 + 目标价 + 承诺收益 + 杠杆
    bad = ("建议买入 SH600519，目标价 2000 元，稳赚不赔，可加杠杆满仓。")
    v = verify(bad, {"evidence": {}})
    assert not v.approved
    ids = {x.id for x in v.violations}
    assert {"H01", "H02", "H03", "B02"} <= ids, ids
    assert v.score < 60
    print(v.report())

    # 2) 合规样本：客观描述 + 风险 + 免责
    good = ("贵州茅台（SH600519）最新收盘价 1680.0 元，PE 28.0，RSI14 为 62.9；"
            "近 60 日涨跌幅 +5.2%。历史波动率 24.5%，最大回撤 -12.3% 提示风险。"
            "本文仅陈述客观数据，不构成投资建议，仅供研究参考。")
    v2 = verify(good, {"evidence": {"close": 1680.0, "pe": 28.0,
                                    "rsi14": 62.9, "chg60": 5.2,
                                    "vol": 24.5, "mdd": -12.3}})
    assert v2.approved, v2.report()
    assert v2.certificate and v2.fingerprint

    # 3) 幻觉数值：给出 evidence 但正文数值对不上
    hallu = ("该股收盘价 9999.0 元，PE 888.0，RSI14 为 5.0，"
             "波动剧烈存在风险。本文不构成投资建议。")
    v3 = verify(hallu, {"evidence": {"close": 1680.0, "pe": 28.0, "rsi14": 62.9}})
    assert not v3.approved and any(x.id == "N02" for x in v3.violations), v3.report()

    # 4) 流式护栏：逐字喂入违规文本，命中即回调
    fired = []
    text, hits = guard_stream(list(bad), on_violation=lambda vs, b: fired.append(vs[0].id))
    assert fired, "流式护栏未触发"
    assert {h.id for h in hits} & {"H01", "H02", "H03"}

    # 5) 自定义约束加载（severity 覆盖）
    import tempfile
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        p = os.path.join(td, "c.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump([{"id": "S02", "severity": "low"}], f)
        cons = load_constraints(p)
        assert cons[0].severity == "low"

    print("nsf_verifier self-check ok "
          f"(bad_score={v.score}, good_approved={v2.approved}, stream_hits={len(hits)})")
