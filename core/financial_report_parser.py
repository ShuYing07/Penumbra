# -*- coding: utf-8 -*-
"""财报与公告深度解析（模块三）。

数据流与降级（诚实标注口径）：
- 报表获取：AKShare 财报/公告接口（stock_financial_report_sina / stock_notice_report）
  → 失败降级到 core.data.service.get_fundamentals 的 F10 快照 → 仍失败返回 note。
- 关键信息提取：优先 LLM（core.model_router.chat，多模型路由），
  无 key/调用失败 → 规则引擎兜底（正则抓业绩变动、合同、风险提示）。
- 输出均为客观数据罗列与信息提取，不构成投资建议。
"""
from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional

log = logging.getLogger("stockai.finreport")


# ---------------------------------------------------------------------------
# 1. 财报/公告获取（多源降级）
# ---------------------------------------------------------------------------

def _cn_code(ticker: str) -> str:
    from core.data.service import normalize_ticker
    t = normalize_ticker(ticker)
    if t.startswith(("SH", "SZ")):
        return t[2:].lstrip("0")  # sina 风格：sh600519 / sz000001
    return t


def get_financial_reports(ticker: str, periods: int = 4) -> dict:
    """获取财报摘要与公告列表。返回 {ok, reports, announcements, fundamentals, note}。

    periods: 期望的报表期数（尽力而为，实际以数据源为准）。
    """
    from core.data import service

    reports: List[dict] = []
    announcements: List[dict] = []
    note: List[str] = []

    # 1) 利润表（AKShare 新浪财报；失败→标注）
    try:
        import akshare as ak
        from core.config import domestic_network
        with domestic_network():
            df = ak.stock_financial_report_sina(
                stock=_cn_code(ticker), symbol="利润表")
        cols = [str(c) for c in df.columns]
        for _, r in df.head(periods).iterrows():
            def _g(k):
                v = r.get(k)
                return None if v is None or str(v) in ("", "-", "nan") else str(v)
            reports.append({
                "period": _g("报告期") or _g("日期"),
                "revenue": _g("营业总收入") or _g("营业收入"),
                "net_profit": _g("净利润") or _g("归属于母公司所有者的净利润"),
                "gross_margin": _g("毛利率"),
            })
        if reports:
            note.append("利润表：新浪财报")
        else:
            note.append("利润表接口返回为空")
    except Exception as e:  # noqa: BLE001
        note.append(f"利润表不可达({type(e).__name__})")

    # 2) 公告（AKShare 个股公告；失败→标注）
    try:
        import akshare as ak
        from core.config import domestic_network
        from datetime import datetime, timedelta
        # 接口需具体日期（YYYYMMDD）；取最近 7 天内的一个日期兜底
        day = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
        with domestic_network():
            df = ak.stock_notice_report(symbol="全部", date=day)
        # 按代码过滤
        code = ticker[-6:] if len(ticker) >= 6 else ticker
        if "代码" in df.columns:
            sub = df[df["代码"].astype(str).str.contains(code, na=False)].head(periods)
        else:
            sub = df.head(periods)
        for _, r in sub.iterrows():
            announcements.append({
                "title": str(r.get("公告标题", "")),
                "date": str(r.get("公告日期", "")),
                "type": str(r.get("公告类型", "")),
            })
        if announcements:
            note.append("公告：AKShare")
        else:
            note.append("公告接口返回为空")
    except Exception as e:  # noqa: BLE001
        note.append(f"公告不可达({type(e).__name__})")

    # 3) F10 快照兜底（估值/行业等基本面）
    fundamentals: dict = {}
    try:
        fundamentals = service.get_fundamentals(ticker) or {}
    except Exception as e:  # noqa: BLE001
        note.append(f"F10 兜底失败({type(e).__name__})")

    ok = bool(reports or announcements or fundamentals)
    if not ok:
        note.append("全部数据源不可达：请在联网后重试，或检查代码是否正确")
    return {"ok": ok, "reports": reports, "announcements": announcements,
            "fundamentals": fundamentals, "note": "；".join(note) or "获取完成"}


# ---------------------------------------------------------------------------
# 2. AI 关键信息提取（LLM 优先，规则兜底）
# ---------------------------------------------------------------------------

def extract_key_info(text: str, ticker: str = "") -> Dict[str, object]:
    """从财报/公告文本提取 {performance, contracts, risks, management_discussion}。

    LLM 不可用时走规则引擎，保证离线也有可用输出（并标注来源）。
    """
    if not text or not text.strip():
        return {"performance": "无文本可解析", "contracts": [], "risks": [],
                "management_discussion": "无文本可解析", "source": "empty"}

    try:
        from core.model_router import chat
        sys_prompt = (
            "你是金融文本信息提取器。从给定财报/公告文本中提取四类信息，"
            "严格遵守：不编造数据；数字保留原文单位；输出 JSON 格式："
            '{"performance":"业绩变动一句话","contracts":["重大合同，含金额与对手方（无则空数组）"],'
            '"risks":["风险提示（无则空数组）"],"management_discussion":"管理层讨论要点（无则空字符串）"}。'
            "仅输出 JSON，不要多余文字。")
        out = chat(f"标的：{ticker}\n文本：\n{text[:4000]}", system=sys_prompt, timeout=30)
        if out:
            import json
            try:
                parsed = json.loads(out)
                parsed["source"] = "llm"
                return {k: parsed.get(k, ([] if k in ("contracts", "risks") else ""))
                        for k in ("performance", "contracts", "risks",
                                  "management_discussion", "source")}
            except Exception:  # noqa: BLE001
                log.warning("LLM 输出非 JSON，回退规则引擎：%s", out[:80])
    except Exception as e:  # noqa: BLE001
        log.warning("LLM 提取失败：%s", e)
    return _rule_extract(text)


def _rule_extract(text: str) -> Dict[str, object]:
    """规则引擎兜底：正则抓业绩/合同/风险/管理层讨论。"""
    s = text
    # 业绩变动
    perf = ""
    m = re.search(r"(?:归属于上市公司股东的)?净利润[^。；\n]{0,60}", s)
    if m:
        perf = m.group(0).strip()
    m2 = re.search(r"营业(?:总)?收入[^。；\n]{0,50}", s)
    if m2 and len(m2.group(0)) > len(perf):
        perf = m2.group(0).strip()
    # 重大合同
    contracts = []
    for m in re.finditer(r"(?:签订|中标|获得)[^。；\n]{0,60}(?:合同|订单)[^。；\n]{0,40}", s):
        contracts.append(m.group(0).strip())
    # 风险提示
    risks = []
    for m in re.finditer(r"(?:风险提示|面临风险|可能影响)[^。；\n]{0,60}", s):
        risks.append(m.group(0).strip())
    # 管理层讨论
    md = ""
    m = re.search(r"(?:管理层讨论|经营情况讨论)[^。；\n]{0,80}", s)
    if m:
        md = m.group(0).strip()
    return {"performance": perf or "（未提取到明确业绩变动）",
            "contracts": contracts[:5],
            "risks": risks[:5],
            "management_discussion": md or "（未提取到管理层讨论）",
            "source": "rule"}


# ---------------------------------------------------------------------------
# 3. 财报摘要卡片（HTML，供 UI 直接渲染）
# ---------------------------------------------------------------------------

def render_report_card(ticker: str, info: Dict[str, object],
                       fundamentals: Optional[dict] = None) -> str:
    """生成财报摘要卡片 HTML：关键指标 + AI 提取要点 + 多期对比占位。"""
    f = fundamentals or {}
    pe = f.get("pe_ttm") or f.get("pe") or "—"
    pb = f.get("pb") or "—"
    mcap = f.get("total_market_cap") or f.get("总市值") or "—"
    industry = f.get("industry") or "—"

    cards = []
    # 估值指标
    cards.append(
        f"<div style='background:#141820;border:1px solid #1E2530;border-radius:10px;"
        f"padding:10px;margin-bottom:8px;'>"
        f"<div style='color:#8B949E;font-size:12px;'>估值指标（数据源：F10/快照）</div>"
        f"<div style='color:#E6EDF3;font-size:13px;'>PE(TTM) <b>{pe}</b>　·　"
        f"PB <b>{pb}</b>　·　总市值 <b>{mcap}</b>　·　行业 <b>{industry}</b></div></div>")

    # 业绩变动
    perf = info.get("performance") or "—"
    cards.append(_section("📊 业绩变动", str(perf), "llm" if info.get("source") == "llm" else "规则提取"))

    # 重大合同
    contracts = info.get("contracts") or []
    c_body = "；".join(f"<li>{c}</li>" for c in contracts) if contracts else "<li>无重大合同记录</li>"
    cards.append(
        f"<div style='background:#141820;border:1px solid #1E2530;border-radius:10px;"
        f"padding:10px;margin-bottom:8px;'>"
        f"<div style='color:#8B949E;font-size:12px;'>📄 重大合同/订单</div>"
        f"<ul style='margin:4px 0;color:#DCE1EB;font-size:13px;'>{c_body}</ul></div>")

    # 风险提示
    risks = info.get("risks") or []
    r_body = "；".join(f"<li>{r}</li>" for r in risks) if risks else "<li>无显著风险提示</li>"
    cards.append(
        f"<div style='background:rgba(255,167,38,0.06);border:1px solid rgba(255,167,38,0.35);"
        f"border-radius:10px;padding:10px;margin-bottom:8px;'>"
        f"<div style='color:#FFA726;font-size:12px;'>⚠️ 风险提示</div>"
        f"<ul style='margin:4px 0;color:#DCE1EB;font-size:13px;'>{r_body}</ul></div>")

    # 管理层讨论
    md = info.get("management_discussion") or "—"
    cards.append(_section("🗣️ 管理层讨论", str(md), ""))

    return ("<div>"
            f"<div style='color:#8B949E;font-size:11px;padding-bottom:4px;'>"
            f"{ticker} · 信息提取来源：{info.get('source', '—')} · 仅供研究，不构成投资建议</div>"
            + "".join(cards) + "</div>")


def _section(title: str, body: str, tag: str) -> str:
    tag_html = (f"<span style='color:#00B4D8;font-size:11px;'>[{tag}]</span>" if tag else "")
    return (f"<div style='background:#141820;border:1px solid #1E2530;border-radius:10px;"
            f"padding:10px;margin-bottom:8px;'>"
            f"<div style='color:#8B949E;font-size:12px;'>{title} {tag_html}</div>"
            f"<div style='color:#DCE1EB;font-size:13px;margin-top:2px;'>{body}</div></div>")


def render_period_compare(reports: List[dict]) -> str:
    """多期报表对比表（HTML）。reports 来自 get_financial_reports()['reports']。"""
    if not reports:
        return "<div style='color:#8B949E;'>暂无多期财报数据（数据源不可达或接口返回为空）</div>"
    rows = ["<tr><th style='padding:4px 10px;color:#8B949E;'>报告期</th>"
            "<th style='padding:4px 10px;color:#8B949E;'>营业总收入</th>"
            "<th style='padding:4px 10px;color:#8B949E;'>净利润</th>"
            "<th style='padding:4px 10px;color:#8B949E;'>毛利率</th></tr>"]
    for r in reports:
        rows.append(
            f"<tr><td style='padding:4px 10px;color:#DCE1EB;'>{r.get('period','—')}</td>"
            f"<td style='padding:4px 10px;color:#DCE1EB;'>{r.get('revenue','—')}</td>"
            f"<td style='padding:4px 10px;color:#DCE1EB;'>{r.get('net_profit','—')}</td>"
            f"<td style='padding:4px 10px;color:#DCE1EB;'>{r.get('gross_margin','—')}</td></tr>")
    return ("<table style='border-collapse:collapse;width:100%;'>" + "".join(rows) + "</table>")


# ---------------------------------------------------------------------------
# 财务比率计算（任务书B·模块四）
# ---------------------------------------------------------------------------

def calculate_ratios(report: Dict[str, object]) -> Dict[str, object]:
    """基于可得字段计算财务比率（盈利能力/偿债能力/运营效率/成长性/估值）。

    report 可用字段：revenue, net_profit, gross_margin, total_assets,
    total_liabilities, equity, operating_cashflow, inventory, accounts_receivable,
    revenue_yoy, profit_yoy, roe, roa, pe, pb, market_cap ...
    缺失字段如实标注（不脑补），返回 {ok, ratios, missing, note}。
    """
    def _f(v):
        try:
            x = float(v)
            return x if x == x else None  # NaN → None
        except (TypeError, ValueError):
            return None

    ratios: Dict[str, float] = {}
    missing: List[str] = []
    R = report or {}

    rev, npf, gm = _f(R.get("revenue")), _f(R.get("net_profit")), _f(R.get("gross_margin"))
    ta, tl, eq = (_f(R.get("total_assets")), _f(R.get("total_liabilities")),
                  _f(R.get("equity")))
    ocf = _f(R.get("operating_cashflow"))
    inv, ar = _f(R.get("inventory")), _f(R.get("accounts_receivable"))
    rev_yoy, npf_yoy = _f(R.get("revenue_yoy")), _f(R.get("profit_yoy"))
    roe, roa = _f(R.get("roe")), _f(R.get("roa"))
    pe, pb, mcap = _f(R.get("pe")), _f(R.get("pb")), _f(R.get("market_cap"))

    # 盈利能力
    if rev and npf is not None:
        ratios["net_margin_pct"] = round(npf / rev * 100, 2)
    else:
        missing.append("net_margin（需营收+净利润）")
    if gm is not None:
        ratios["gross_margin_pct"] = gm
    if roe is not None:
        ratios["roe_pct"] = roe
    if roa is not None:
        ratios["roa_pct"] = roa
    if ocf is not None and npf is not None and npf != 0:
        ratios["ocf_to_profit"] = round(ocf / npf, 2)
    elif ocf is None:
        missing.append("ocf_to_profit（需经营现金流）")

    # 偿债能力
    if ta and tl is not None:
        ratios["debt_to_assets_pct"] = round(tl / ta * 100, 2)
    else:
        missing.append("debt_to_assets（需总资产+总负债）")
    if ta and eq is not None and eq != 0:
        ratios["assets_to_equity"] = round(ta / eq, 2)
    elif eq is None:
        missing.append("assets_to_equity（需净资产）")

    # 运营效率
    if rev and inv is not None and inv != 0:
        ratios["inventory_turnover"] = round(rev / inv, 2)
    if rev and ar is not None and ar != 0:
        ratios["receivable_turnover"] = round(rev / ar, 2)
    if rev and ta is not None and ta != 0:
        ratios["asset_turnover"] = round(rev / ta, 2)

    # 成长性
    if rev_yoy is not None:
        ratios["revenue_yoy_pct"] = rev_yoy
    if npf_yoy is not None:
        ratios["profit_yoy_pct"] = npf_yoy

    # 估值
    if pe is not None:
        ratios["pe"] = pe
    if pb is not None:
        ratios["pb"] = pb
    if mcap and npf is not None and npf != 0:
        ratios["pe_implied"] = round(mcap / npf, 2)

    if not ratios:
        return {"ok": False, "ratios": {}, "missing": missing,
                "note": "财报字段不足，无法计算比率（数据不足）"}
    return {"ok": True, "ratios": ratios, "missing": missing,
            "note": "比率基于可得字段计算；缺失项已如实标注，不构成估值建议"}


def render_ratios_card(ratios_out: Dict[str, object]) -> str:
    """财务比率卡片（HTML）。"""
    if not ratios_out.get("ok"):
        return (f"<div style='color:#8B949E;'>{ratios_out.get('note', '')}</div>"
                + ("<p style='color:#FFA726;'>缺失字段：" + "、".join(
                    ratios_out.get("missing", [])) + "</p>" if ratios_out.get("missing") else ""))
    rows = ["<tr><th style='padding:4px 10px;color:#8B949E;'>比率</th>"
            "<th style='padding:4px 10px;color:#8B949E;'>值</th></tr>"]
    for k, v in ratios_out["ratios"].items():
        rows.append(f"<tr><td style='padding:4px 10px;color:#8B949E;'>{k}</td>"
                    f"<td style='padding:4px 10px;color:#DCE1EB;'>{v}</td></tr>")
    miss = ("<p style='color:#FFA726;'>未计算：" + "、".join(
        ratios_out.get("missing", [])) + "</p>" if ratios_out.get("missing") else "")
    return ("<h3 style='color:#DCE1EB;'>📐 财务比率</h3>"
            f"<table style='border-collapse:collapse;width:100%;'>" + "".join(rows)
            + "</table>" + miss + f"<p style='color:#8B949E;font-size:12px;'>{ratios_out.get('note','')}</p>")


# ---------------------------------------------------------------------------
# 5 年 DCF 估值（任务书B·模块四）
# ---------------------------------------------------------------------------

def build_dcf_model(financials: Dict[str, object] | None = None) -> Dict[str, object]:
    """5 年自由现金流折现（含乐观/中性/悲观三情景 + 敏感性）。

    financials 可用字段：fcf（基期自由现金流，默认 1.0 单位）、
    growth_rate（5年增长率%，默认 5）、discount_rate（折现率%，默认 10）、
    terminal_growth（永续增长率%，默认 2.5）。
    未提供关键假设时使用默认值并如实标注"假设值"——本函数为教学/研究演示，
    不构成任何投资建议或估值结论。
    """
    def _f(v, d):
        try:
            x = float(v)
            return x if x == x else d
        except (TypeError, ValueError):
            return d

    fcf0 = _f((financials or {}).get("fcf"), 1.0)
    g = _f((financials or {}).get("growth_rate"), 5.0) / 100.0
    r = _f((financials or {}).get("discount_rate"), 10.0) / 100.0
    tg = _f((financials or {}).get("terminal_growth"), 2.5) / 100.0
    if r <= tg:
        r = tg + 0.01

    def _value(g_used, r_used, tg_used) -> float:
        pv = 0.0
        fcf = fcf0
        for t in range(1, 6):
            fcf = fcf * (1 + g_used)
            pv += fcf / (1 + r_used) ** t
        tv = fcf * (1 + tg_used) / (r_used - tg_used)
        pv += tv / (1 + r_used) ** 5
        return pv

    scenarios = {
        "pessimistic": round(_value(g * 0.5, r * 1.2, tg * 0.6), 2),
        "base": round(_value(g, r, tg), 2),
        "optimistic": round(_value(g * 1.5, r * 0.85, tg * 1.4), 2),
    }
    # 敏感性：增长率×折现率 3×3 网格
    sensitivity = {}
    for gg in (0.0, g, g * 2):
        for rr in (r * 0.85, r, r * 1.2):
            sensitivity[f"g={round(gg*100,1)}%/r={round(rr*100,1)}%"] = round(_value(gg, rr, tg), 2)
    return {
        "ok": True,
        "fair_value_base": scenarios["base"],
        "scenarios": scenarios,
        "sensitivity": sensitivity,
        "assumptions": {"fcf0": fcf0, "growth_rate_pct": round(g * 100, 1),
                        "discount_rate_pct": round(r * 100, 1),
                        "terminal_growth_pct": round(tg * 100, 1)},
        "note": "DCF 结果依赖自由现金流与折现率假设；未提供输入时使用默认假设值。"
                "仅供研究与教学演示，不构成投资建议或目标价。",
    }


def render_dcf_card(dcf: Dict[str, object]) -> str:
    """DCF 估值卡片（HTML）。"""
    if not dcf.get("ok"):
        return f"<div style='color:#8B949E;'>{dcf.get('note', '')}</div>"
    sc = dcf["scenarios"]
    rows = ["<tr><th style='padding:4px 10px;color:#8B949E;'>情景</th>"
            "<th style='padding:4px 10px;color:#8B949E;'>内在价值（单位）</th></tr>"]
    for k, v in sc.items():
        rows.append(f"<tr><td style='padding:4px 10px;color:#8B949E;'>{k}</td>"
                    f"<td style='padding:4px 10px;color:#DCE1EB;'>{v}</td></tr>")
    asm = "；".join(f"{k}={v}" for k, v in dcf["assumptions"].items())
    return ("<h3 style='color:#DCE1EB;'>💵 5年 DCF 估值</h3>"
            f"<table style='border-collapse:collapse;width:100%;'>" + "".join(rows)
            + "</table>"
            + f"<p style='color:#8B949E;font-size:12px;'>假设：{asm}</p>"
            + f"<p style='color:#FFA726;font-size:12px;'>{dcf.get('note','')}</p>")


def build_report_card_html(ticker: str) -> str:
    """财报摘要卡片聚合（0.8.0 UI 入口）：
    财报摘要（业绩变动/合同/风险/管理层讨论）→ 多期对比 → 财务比率 → 5年DCF。
    数据源不可达时逐段降级标注，不脑补。返回暗色主题 HTML。"""
    from core.fundamental_analyzer import analyze_fundamentals, render_fundamental_card

    parts: List[str] = []
    reports = get_financial_reports(ticker, periods=4)
    reps = reports.get("reports") or []
    note = list(reports.get("note") or [])
    fundamentals = reports.get("fundamentals") or {}

    # 1) 关键信息提取（LLM → 规则兜底）
    if reps:
        latest = f"{reps[0].get('period','')}营收{reps[0].get('revenue','—')}、"
        latest += f"净利润{reps[0].get('net_profit','—')}、毛利率{reps[0].get('gross_margin','—')}"
        info = extract_key_info(latest, ticker)
        parts.append(render_report_card(ticker, info, reports))
        parts.append(render_period_compare(reps))
    else:
        note.append("财报接口不可达，跳过摘要与多期对比")

    # 2) 财务比率（可得字段如实计算 + 缺失标注）
    if reps:
        parts.append(render_ratios_card(calculate_ratios(reps[0])))
    else:
        parts.append("<div style='color:#8B949E;'>财务比率：无报表数据</div>")

    # 3) 5 年 DCF（基于可得字段；数据不足给中性演示标注）
    f = {}
    if reps:
        f = {"revenue": reps[0].get("revenue"), "net_profit": reps[0].get("net_profit"),
             "gross_margin": reps[0].get("gross_margin"),
             "period": reps[0].get("period", "")}
    parts.append(render_dcf_card(build_dcf_model(f)))

    # 4) 基本面健康度卡片（估值/增速/评分/同行）
    try:
        ana = analyze_fundamentals(ticker)
        parts.append(render_fundamental_card(ana))
    except Exception as e:  # noqa: BLE001
        note.append(f"基本面卡片失败({type(e).__name__})")

    if note:
        parts.insert(0, f"<div style='color:#FFA726;font-size:12px;'>"
                    f"⚠️ {'；'.join(note)}</div>")
    parts.append("<div style='color:#8B949E;font-size:12px;'>以上为客观数据展示，"
                 "不构成投资建议。</div>")
    return "<div style='line-height:1.6;'>" + "".join(parts) + "</div>"


if __name__ == "__main__":
    info = extract_key_info("公司2026年半年度净利润同比增长15%，签订重大销售合同3亿元，"
                            "管理层讨论称海外业务拓展顺利。风险提示：行业竞争加剧。")
    print(info)
