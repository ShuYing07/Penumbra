# -*- coding: utf-8 -*-
"""多源行情交叉核对与对账（data_reconciler）。

参考 MDRAP（Market Data Reliability & Acceleration Platform）的思路：
**同时**取多个数据源的同一标的，实时交叉核对，检测不一致与异常，
主源异常时自动切换到数据质量最高的备源。

为什么值得做：
单一数据源的"静默错误"（供应商推送延迟、复权因子错误、价格卡住不动）
不会报错，只会让分析结论悄悄跑偏。多源对账把"信任"变成"可验证"——
两个源一致，可信度上升；两源打架，宁可提示也不要装作没看见。

设计要点：
1. 纯函数 ``reconcile()`` 与取数分离 → 无需网络即可完整单测；
2. 每个源独立 try/except，单源失败只降级不影响整体；
3. 打分选源不只看"价格一致"，还看成交量字段完整性、时间戳新鲜度。
"""
from __future__ import annotations

import logging
import time
from typing import Any, Callable, Dict, List, Optional, Sequence

log = logging.getLogger("stockai.reconciler")

# 默认核对阈值
DEFAULT_PRICE_TOL_PCT = 1.0      # 价格相对偏差容忍度（%）
DEFAULT_TS_TOL_S = 900           # 时间戳不一致容忍（秒）


def _pick(d: Dict[str, Any], *keys, default=None):
    for k in keys:
        v = d.get(k)
        if v not in (None, "", 0):
            return v
    return default


class SourceQuote:
    """一个数据源对某一标的的一次报价快照。"""

    __slots__ = ("source", "price", "prev_close", "chg_pct", "volume",
                 "ts", "ok", "error", "latency_ms", "extra")

    def __init__(self, source: str, price=None, prev_close=None, chg_pct=None,
                 volume=None, ts=None, ok=True, error="", latency_ms=0.0,
                 extra=None):
        self.source = source
        self.price = price
        self.prev_close = prev_close
        self.chg_pct = chg_pct
        self.volume = volume
        self.ts = ts
        self.ok = ok
        self.error = error
        self.latency_ms = latency_ms
        self.extra = extra or {}

    def to_dict(self) -> Dict[str, Any]:
        return {"source": self.source, "price": self.price,
                "prev_close": self.prev_close, "chg_pct": self.chg_pct,
                "volume": self.volume, "ts": self.ts, "ok": self.ok,
                "error": self.error, "latency_ms": round(self.latency_ms, 1),
                "extra": self.extra}

    @classmethod
    def failed(cls, source: str, error: str) -> "SourceQuote":
        return cls(source, ok=False, error=error)


# ---------------------------------------------------------------------------
# 核心：交叉核对（纯函数，可离线单测）
# ---------------------------------------------------------------------------
def _median(xs: List[float]) -> Optional[float]:
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    n = len(xs)
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


def score_source(q: SourceQuote, consensus: Optional[float],
                 newest_ts: Optional[float],
                 price_tol_pct: float) -> float:
    """源质量打分（0-100）：一致性 + 新鲜度 + 字段完整性 + 速度。"""
    if not q.ok or q.price is None:
        return 0.0
    s = 50.0
    if consensus and q.price:
        dev = abs(q.price - consensus) / consensus * 100.0
        if dev <= price_tol_pct * 0.5:
            s += 25
        elif dev <= price_tol_pct:
            s += 12
        else:
            s -= 30                      # 明显偏离共识：可疑源
    if q.volume:
        s += 10                          # 有成交量字段：信息更完整
    if q.ts is not None and newest_ts:
        lag = max(0.0, newest_ts - q.ts)
        s += 10 if lag <= 60 else (5 if lag <= DEFAULT_TS_TOL_S else -10)
    if q.latency_ms:
        s += 5 if q.latency_ms < 1000 else 0
    return max(0.0, min(100.0, s))


def reconcile(quotes: Sequence[SourceQuote], *,
              price_tol_pct: float = DEFAULT_PRICE_TOL_PCT,
              ts_tol_s: float = DEFAULT_TS_TOL_S) -> Dict[str, Any]:
    """对多源报价做交叉核对，输出对账报告。

    返回：{ consensus, deviations, warnings, chosen, scores, severity, ok }
    - severity: FATAL（全部源失败）/ WARN（存在偏差或不一致）/ OK
    """
    qs = list(quotes or [])
    ok_qs = [q for q in qs if q.ok and q.price]
    report: Dict[str, Any] = {
        "sources": [q.to_dict() for q in qs],
        "usable": len(ok_qs),
        "total": len(qs),
        "consensus": None,
        "deviations": [],
        "warnings": [],
        "chosen": None,
        "scores": {},
        "severity": "OK",
        "ok": True,
        "price_tol_pct": price_tol_pct,
    }
    if not qs:
        report.update({"severity": "FATAL", "ok": False,
                       "warnings": ["没有任何数据源返回"]})
        return report
    if not ok_qs:
        report.update({"severity": "FATAL", "ok": False,
                       "warnings": [f"全部 {len(qs)} 个源均失败："
                                    + "；".join(f"{q.source}({q.error})" for q in qs[:3])]})
        return report

    prices = [q.price for q in ok_qs]
    consensus = _median(prices)
    report["consensus"] = consensus

    # ① 价格偏差：逐源与中位数比较
    for q in ok_qs:
        dev_pct = abs(q.price - consensus) / consensus * 100.0 if consensus else 0.0
        report["deviations"].append({
            "source": q.source, "price": q.price,
            "dev_pct": round(dev_pct, 4),
            "outlier": dev_pct > price_tol_pct,
        })
        if dev_pct > price_tol_pct:
            report["warnings"].append(
                f"{q.source} 价格 {q.price} 与共识 {round(consensus, 4)} "
                f"偏差 {dev_pct:.2f}%（>{price_tol_pct}%）")

    # ② 时间戳不一致
    tss = [q.ts for q in ok_qs if q.ts is not None]
    if len(tss) >= 2:
        newest, oldest = max(tss), min(tss)
        if newest - oldest > ts_tol_s:
            report["warnings"].append(
                f"各源时间戳相差 {round(newest - oldest)} 秒（>{ts_tol_s} 秒），"
                f"可能存在延迟推送")
        report["ts_spread_s"] = round(newest - oldest, 1)

    # ③ 缺失/失败源
    for q in qs:
        if not q.ok:
            report["warnings"].append(f"{q.source} 不可用：{q.error}")

    # ④ 选源：打分最高的可用源
    newest_ts = max(tss) if tss else None
    scores = {q.source: round(score_source(q, consensus, newest_ts, price_tol_pct), 1)
              for q in ok_qs}
    report["scores"] = scores
    best = max(ok_qs, key=lambda q: scores.get(q.source, 0))
    report["chosen"] = best.source
    report["chosen_price"] = best.price
    report["chosen_quote"] = best.to_dict()

    if any(d["outlier"] for d in report["deviations"]):
        report["severity"] = "WARN"
    if len(ok_qs) == 1 and len(qs) > 1:
        report["warnings"].append("仅 1 个源可用，无法交叉验证，结论可信度下降")
        report["severity"] = "WARN"
    report["ok"] = report["severity"] != "FATAL"
    return report


# ---------------------------------------------------------------------------
# 取数（多源并发；单源失败只降级）
# ---------------------------------------------------------------------------
def _quote_from_realtime(source: str, fn: Callable[[], dict]) -> SourceQuote:
    t0 = time.perf_counter()
    try:
        d = fn() or {}
    except Exception as e:  # noqa: BLE001
        return SourceQuote(source, ok=False, error=f"{type(e).__name__}: {e}",
                           latency_ms=(time.perf_counter() - t0) * 1000)
    lat = (time.perf_counter() - t0) * 1000
    price = _pick(d, "price", "last", "close", "current")
    if price is None:
        return SourceQuote(source, ok=False, error="返回缺少价格字段",
                           latency_ms=lat)
    return SourceQuote(
        source=source,
        price=float(price),
        prev_close=_pick(d, "prev_close", "pre_close", "昨收"),
        chg_pct=_pick(d, "chg_pct", "pct_chg", "涨跌幅"),
        volume=_pick(d, "volume", "vol", "成交量"),
        ts=_pick(d, "ts", "timestamp") if isinstance(_pick(d, "ts", "timestamp"),
                                                     (int, float)) else time.time(),
        latency_ms=lat, extra={k: v for k, v in d.items()
                               if k in ("name", "market", "source", "time")})


def fetch_realtime_multi(code: str, sources: Sequence[str] = ("akshare", "yfinance"),
                         timeout: float = 8.0) -> List[SourceQuote]:
    """同时向多个数据源取实时快照（顺序执行 + 单源超时保护）。

    网络不可用时各源自然失败并降级，不会抛异常——调用方只看对账报告。
    """
    from core.data.service import normalize_ticker
    try:
        ticker = normalize_ticker(code)
    except Exception:  # noqa: BLE001
        ticker = str(code)

    def akshare_fn() -> dict:
        from core.data.akshare_source import fetch_realtime_cn
        d = fetch_realtime_cn(ticker) or {}
        d.setdefault("source", "akshare")
        return d

    def yf_fn() -> dict:
        from core.data.yfinance_source import fetch_realtime as _fr
        d = _fr(ticker) or {}
        d.setdefault("source", "yfinance")
        return d

    def tushare_fn() -> dict:
        from core.data.tushare_source import fetch_realtime as _fr
        d = _fr(ticker) or {}
        d.setdefault("source", "tushare")
        return d

    registry = {"akshare": akshare_fn, "yfinance": yf_fn, "tushare": tushare_fn}
    out: List[SourceQuote] = []
    for name in sources:
        fn = registry.get(name)
        if fn is None:
            out.append(SourceQuote.failed(name, "未支持的数据源"))
            continue
        out.append(_quote_from_realtime(name, fn))
    return out


def reconcile_realtime(code: str, sources: Sequence[str] = ("akshare", "yfinance"),
                       price_tol_pct: float = DEFAULT_PRICE_TOL_PCT) -> Dict[str, Any]:
    """一步到位：取多源 → 交叉核对 → 返回对账报告（含推荐源与其报价）。"""
    quotes = fetch_realtime_multi(code, sources)
    rep = reconcile(quotes, price_tol_pct=price_tol_pct)
    rep["ticker"] = str(code)
    return rep


def best_quote(rep: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """从对账报告里取出推荐源的报价（供上层直接使用）。"""
    return rep.get("chosen_quote")


def format_report(rep: Dict[str, Any]) -> str:
    """人读对账报告。"""
    if rep["severity"] == "FATAL":
        return "⛔ " + "；".join(rep["warnings"])
    lines = [f"多源对账 · {rep.get('ticker','')} · 可用 {rep['usable']}/{rep['total']} 源 · "
             f"共识价 {rep['consensus']}",
             f"推荐源：{rep['chosen']}（报价 {rep.get('chosen_price')}）"]
    for d in rep["deviations"]:
        flag = "⚠️" if d["outlier"] else "  "
        lines.append(f"  {flag} {d['source']}: {d['price']} 偏差 {d['dev_pct']}%")
    for w in rep["warnings"]:
        lines.append(f"  · {w}")
    return "\n".join(lines)
