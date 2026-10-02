# -*- coding: utf-8 -*-
"""财报摘要卡片（report_summary_card）：把财报解析器的输出组装成
结构化摘要卡片 + 多期对比数据 + 同行对比雷达数据，供 UI 直接渲染。

复用 core.financial_report_parser 的 get_financial_reports / calculate_ratios /
build_dcf_model / extract_key_info，不重复实现取数与计算。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.financial_report_parser import (calculate_ratios, build_dcf_model,
                                          extract_key_info, get_financial_reports)


class ReportSummaryCard:
    """财报摘要卡片：单只股票一期的结构化摘要。"""

    def __init__(self, ticker: str = "", period: str = "", revenue: float = 0.0,
                 net_profit: float = 0.0, gross_margin: float = 0.0,
                 roe: float = 0.0, eps: float = 0.0, yoy_revenue: float = 0.0,
                 yoy_profit: float = 0.0, debt_ratio: float = 0.0,
                 key_points: Optional[List[str]] = None,
                 risks: Optional[List[str]] = None,
                 dcf: Optional[Dict[str, Any]] = None,
                 source: str = "", fetched_at: str = ""):
        self.ticker = ticker
        self.period = period
        self.revenue = revenue
        self.net_profit = net_profit
        self.gross_margin = gross_margin
        self.roe = roe
        self.eps = eps
        self.yoy_revenue = yoy_revenue
        self.yoy_profit = yoy_profit
        self.debt_ratio = debt_ratio
        self.key_points = key_points or []
        self.risks = risks or []
        self.dcf = dcf or {}
        self.source = source
        self.fetched_at = fetched_at

    def to_dict(self) -> Dict[str, Any]:
        return {k: getattr(self, k) for k in (
            "ticker", "period", "revenue", "net_profit", "gross_margin", "roe",
            "eps", "yoy_revenue", "yoy_profit", "debt_ratio", "key_points",
            "risks", "dcf", "source", "fetched_at")}


def _ratios(report: dict) -> dict:
    """解包 calculate_ratios 的 {ok, ratios, missing, note}，并合并原始字段
    （revenue/net_profit/eps/gross_margin/roe…），调用方用哪个键都拿得到。"""
    out = calculate_ratios(report)
    ratios = out.get("ratios") if isinstance(out, dict) else None
    base = dict(ratios) if isinstance(ratios, dict) else {}
    for k in ("revenue", "net_profit", "eps", "gross_margin", "roe", "debt_ratio",
              "revenue_yoy", "profit_yoy", "market_cap"):
        if k in (report or {}):
            v = report.get(k)
            if v is not None:
                base.setdefault(k, v)
    return base


def build_summary_card(ticker: str, periods: int = 4) -> ReportSummaryCard:
    """一站式：取数 → 比率 → DCF → AI要点 → 组装卡片。

    网络不可用时（mock/离线）自动降级：返回含空字段但结构完整的卡片，
    并标注 source/fetched_at，绝不抛异常。
    """
    card = ReportSummaryCard(ticker=ticker, source="AKShare/Sina",
                             fetched_at="")
    try:
        import time
        from core.config import now_cn
        card.fetched_at = now_cn()
        reports = get_financial_reports(ticker, periods=periods)
        if not reports:
            return card
        latest = reports[0]
        ratios = _ratios(latest)
        card.period = str(latest.get("report_date") or latest.get("period") or "")
        card.revenue = float(latest.get("revenue") or latest.get("营业收入")
                             or ratios.get("revenue") or 0)
        card.net_profit = float(latest.get("net_profit")
                                or latest.get("净利润") or ratios.get("net_profit") or 0)
        card.gross_margin = float(ratios.get("gross_margin") or 0)
        card.roe = float(ratios.get("roe") or 0)
        card.eps = float(ratios.get("eps") or 0)
        card.debt_ratio = float(ratios.get("debt_ratio") or 0)
        # 同比：最新期 vs 上期
        if len(reports) >= 2:
            prev = _ratios(reports[1])
            pr = float(prev.get("revenue") or 0)
            pp = float(prev.get("net_profit") or 0)
            if pr:
                card.yoy_revenue = (card.revenue - pr) / abs(pr) * 100
            if pp:
                card.yoy_profit = (card.net_profit - pp) / abs(pp) * 100
        # AI 要点：文本摘要规则抽取（无外部依赖，离线可用）
        info = extract_key_info("", ticker)
        card.key_points = [str(x) for x in (info.get("highlights")
                                            or info.get("points") or [])][:6]
        card.risks = [str(x) for x in (info.get("risks") or [])][:4]
        # DCF：build_dcf_model 接受 dict 假设参数（list 会抛 → 不阻塞卡片）
        try:
            card.dcf = build_dcf_model(latest)
        except Exception:  # noqa: BLE001
            card.dcf = {}
    except Exception:  # noqa: BLE001
        pass
    return card


def multi_period_compare(reports: List[dict]) -> List[dict]:
    """多期对比数据：每期 {period, revenue, net_profit, gross_margin, roe, eps}。

    供 UI 画营收/利润/毛利率趋势与表格。
    """
    out = []
    for r in (reports or [])[:6]:
        ratios = _ratios(r)
        out.append({
            "period": str(r.get("report_date") or r.get("period") or ""),
            "revenue": float(ratios.get("revenue") or 0),
            "net_profit": float(ratios.get("net_profit") or 0),
            "gross_margin": float(ratios.get("gross_margin") or 0),
            "roe": float(ratios.get("roe") or 0),
            "eps": float(ratios.get("eps") or 0),
        })
    return out


def peer_compare(ticker: str, peers: List[str]) -> Dict[str, Any]:
    """同行对比（确定性规则，离线可测）：返回各同行最新期核心比率，
    供 UI 画雷达图（gross_margin / roe / eps / debt_ratio / growth）。

    数据源失败时该同行条目降级为 {error: ...}，不影响整体。
    """
    out: Dict[str, Any] = {"ticker": ticker, "peers": []}
    for p in peers:
        entry: Dict[str, Any] = {"ticker": p}
        try:
            reports = get_financial_reports(p, periods=1)
            if reports:
                ratios = _ratios(reports[0])
                entry.update({
                    "gross_margin": float(ratios.get("gross_margin") or 0),
                    "roe": float(ratios.get("roe") or 0),
                    "eps": float(ratios.get("eps") or 0),
                    "debt_ratio": float(ratios.get("debt_ratio") or 0),
                    "revenue": float(ratios.get("revenue") or 0),
                })
            else:
                entry["error"] = "无数据"
        except Exception:  # noqa: BLE001
            entry["error"] = "获取失败"
        out["peers"].append(entry)
    return out
