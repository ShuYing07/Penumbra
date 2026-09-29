# -*- coding: utf-8 -*-
"""基本面分析引擎（模块九）。

基于程序取得的财报/估值数据做确定性分析：
- analyze_fundamentals(code)：
  1. 估值快照（PE/PB/市值/行业，来源 F10 / yfinance）；
  2. 多期利润表（新浪财报）计算营收/净利增速、毛利率；
  3. 财务健康度评分 0-100（按可用维度独立计分，缺失维度明确标注、不脑补）；
  4. 同行对比（同市场同行业标的的 PE/PB 中位数，尽力而为）。

所有数字均来自程序取得的数据，评分只做数据描述，不构成投资建议。
"""
from __future__ import annotations

import logging
from typing import List

from core.data import service

log = logging.getLogger("stockai.fundamental")


def _num(v, scale: float = 1.0):
    """字符串/数字 → float；失败返回 None。scale 用于单位换算（如 万 → 元）。"""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v) * scale
    s = str(v).strip().replace(",", "")
    if s in ("", "-", "nan", "None", "--"):
        return None
    try:
        return float(s) * scale
    except Exception:  # noqa: BLE001
        return None


def _growth(cur, prev):
    """同比/环比增速（%）；任一侧缺失返回 None。"""
    if cur is None or prev is None or prev == 0:
        return None
    return (cur - prev) / abs(prev) * 100.0


def analyze_fundamentals(ticker: str) -> dict:
    """返回 {ok, score, grade, dimensions, valuation, peers, reports, note}。

    dimensions: [{name, value, score, note}]，score∈[0,100]，-1 表示数据不足不参与评分。
    """
    from core.financial_report_parser import get_financial_reports

    ticker = ticker.upper()
    reports = get_financial_reports(ticker, periods=4)
    funda = reports.get("fundamentals") or {}
    note: List[str] = list(reports.get("note") or [])

    # ---------- 1. 估值快照 ----------
    pe = _num(funda.get("pe_ttm"))
    pb = _num(funda.get("pb"))
    mcap = _num(funda.get("total_market_cap"))
    industry = funda.get("industry") or funda.get("sector") or funda.get("industryKey") or ""
    valuation = {
        "pe_ttm": round(pe, 2) if pe is not None else None,
        "pb": round(pb, 2) if pb is not None else None,
        "market_cap": mcap,
        "industry": industry,
        "name": funda.get("name") or "",
    }

    # ---------- 2. 多期利润表指标 ----------
    reps = reports.get("reports") or []
    dims: List[dict] = []
    if len(reps) >= 2:
        r0, r1 = reps[0], reps[1]
        rev0, rev1 = _num(r0.get("revenue")), _num(r1.get("revenue"))
        np0, np1 = _num(r0.get("net_profit")), _num(r1.get("net_profit"))
        g_rev = _growth(rev0, rev1)
        g_np = _growth(np0, np1)
        if g_rev is not None:
            score = 100 if g_rev > 0 else (50 if g_rev == 0 else 0)
            dims.append({"name": "营收增速", "value": f"{g_rev:+.1f}%",
                         "score": score,
                         "note": f"{r0.get('period','?')} vs {r1.get('period','?')}"})
        else:
            dims.append({"name": "营收增速", "value": "数据不足", "score": -1,
                         "note": "两期报表营收字段缺失"})
        if g_np is not None:
            score = 100 if g_np > 0 else (50 if g_np == 0 else 0)
            dims.append({"name": "净利增速", "value": f"{g_np:+.1f}%",
                         "score": score,
                         "note": f"{r0.get('period','?')} vs {r1.get('period','?')}"})
        else:
            dims.append({"name": "净利增速", "value": "数据不足", "score": -1,
                         "note": "两期报表净利字段缺失"})
    else:
        note.append(f"利润表期数不足（{len(reps)} 期），增速维度无法计算")

    gm = _num(reps[0].get("gross_margin")) if reps else None
    if gm is not None:
        score = 100 if gm >= 30 else (75 if gm >= 20 else (50 if gm >= 10 else 25))
        dims.append({"name": "毛利率", "value": f"{gm:.1f}%",
                     "score": score, "note": f"{reps[0].get('period','?')}"})
    else:
        dims.append({"name": "毛利率", "value": "数据不足", "score": -1,
                     "note": "报表未含毛利率字段"})

    # 估值维度（相对水平说明，不含绝对判断）
    if pe is not None:
        dims.append({"name": "市盈率(PE-TTM)", "value": f"{pe:.1f}",
                     "score": -1, "note": "估值高低需结合行业与盈利质量判断"})
    if pb is not None:
        dims.append({"name": "市净率(PB)", "value": f"{pb:.2f}",
                     "score": -1, "note": "仅作数据展示"})

    # ---------- 3. 财务健康度评分（可用维度归一） ----------
    scored = [d for d in dims if d["score"] >= 0]
    if scored:
        score = int(round(sum(d["score"] for d in scored) / len(scored)))
        grade = "优" if score >= 80 else ("良" if score >= 60 else (
            "中" if score >= 40 else "待观察"))
    else:
        score, grade = None, "数据不足"
    dims.append({"name": "综合健康度", "value": f"{score}/100" if score is not None else "—",
                 "score": score if score is not None else -1,
                 "note": f"基于 {len(scored)} 个可得维度" if scored else "无可得分维度"})

    # ---------- 4. 同行对比（同市场同行业，尽力而为） ----------
    peers: dict = {}
    if industry and ticker.startswith(("SH", "SZ")):
        try:
            from core.screener import _index
            idx = _index()
            same = [s for s in idx if s.get("board") == industry and s.get("market") == "A股"
                    and s.get("code") != ticker]
            if not same:
                same = [s for s in idx if s.get("industry") == industry
                        and s.get("market") == "A股" and s.get("code") != ticker]
            peers = {"count": len(same),
                     "codes": [s["code"] for s in same[:20]],
                     "note": "同行 PE/PB 需逐只拉取行情快照（网络可用时自动填充）"}
        except Exception as e:  # noqa: BLE001
            peers = {"count": 0, "note": f"同行检索失败：{type(e).__name__}"}
    else:
        peers = {"count": 0, "note": "无行业字段或非A股标的，跳过同行对比"}

    ok = bool(scored or pe or pb)
    return {
        "ok": ok,
        "ticker": ticker,
        "score": score,
        "grade": grade,
        "dimensions": dims,
        "valuation": valuation,
        "peers": peers,
        "reports": reps,
        "note": note,
    }


def render_fundamental_card(analysis: dict) -> str:
    """HTML 摘要卡片（暗色主题）。"""
    if not analysis.get("ok"):
        notes = "；".join(analysis.get("note") or []) or "无可用数据"
        return (f"<div style='color:#FFA726;padding:8px 12px;'>⚠️ 基本面数据不可用：{notes}"
                f"<br/>请检查网络后重试，或确认代码正确。</div>")

    v = analysis.get("valuation") or {}
    rows = []
    rows.append("<table style='border-collapse:collapse;width:100%;'>")
    rows.append("<tr style='background:#1E2530;'><td style='padding:6px 10px;color:#8B949E;'>估值指标</td>"
                "<td style='padding:6px 10px;color:#DCE1EB;'>数值</td></tr>")
    for label, val in (("市盈率(PE-TTM)", v.get("pe_ttm")), ("市净率(PB)", v.get("pb")),
                       ("总市值", v.get("market_cap")), ("行业", v.get("industry") or "—")):
        txt = "—" if val is None else (f"{val:,.0f}" if isinstance(val, float) and val > 1e4
                                       else str(val))
        rows.append(f"<tr><td style='padding:6px 10px;color:#8B949E;'>{label}</td>"
                    f"<td style='padding:6px 10px;color:#DCE1EB;'>{txt}</td></tr>")
    rows.append("</table>")

    score = analysis.get("score")
    grade = analysis.get("grade", "—")
    bar = ""
    if score is not None:
        color = "#00C853" if score >= 60 else ("#FFA726" if score >= 40 else "#FF1744")
        bar = (f"<div style='margin:8px 0;'>财务健康度 <b>{score}/100</b>（{grade}）"
               f"<div style='background:#1E2530;border-radius:4px;height:8px;'>"
               f"<div style='background:{color};border-radius:4px;height:8px;"
               f"width:{score}%;'></div></div></div>")

    dim_html = []
    for d in analysis.get("dimensions") or []:
        if d["name"] == "综合健康度":
            continue
        val = d.get("value", "—")
        dim_html.append(f"<div style='display:flex;justify-content:space-between;"
                        f"padding:3px 0;border-bottom:1px solid #1E2530;'>"
                        f"<span style='color:#8B949E'>{d['name']}</span>"
                        f"<span style='color:#DCE1EB'>{val} "
                        f"<span style='color:#6B7488;font-size:11px'>{d.get('note','')}</span>"
                        f"</span></div>")

    peers = analysis.get("peers") or {}
    peer_note = peers.get("note", "")
    peers_html = (f"<div style='color:#6B7488;font-size:12px;margin-top:6px;'>"
                  f"👥 同行对比：{peers.get('count', 0)} 只同行业标的（{peer_note}）</div>")

    return (
        f"<div style='line-height:1.6;'>"
        f"{bar}"
        f"{''.join(dim_html)}"
        f"<div style='margin-top:8px;'>{''.join(rows)}</div>"
        f"{peers_html}"
        f"<div style='color:#6B7488;font-size:12px;margin-top:6px;'>"
        f"来源：{'；'.join(analysis.get('note') or []) or '程序取得'}</div>"
        f"<div style='color:#8B949E;font-size:12px;margin-top:4px;'>"
        f"以上为客观数据展示，不构成投资建议。</div></div>"
    )
