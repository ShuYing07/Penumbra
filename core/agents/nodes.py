# -*- coding: utf-8 -*-
"""LangGraph 节点函数。每个节点：读状态中的"程序事实" → 调 LLM → schema 校验 → 局部更新。"""
from __future__ import annotations

import logging
from functools import partial

from core.agents import prompts as P
from core.agents.schemas import AnalystSignal, Debate, RiskDecision, TraderPlan

log = logging.getLogger("stockai.agents")


def _run(runner, node: str, system: str, user: str, schema):
    """调 LLM + 校验；任何异常降级，绝不让单节点拖垮整条管线。"""
    try:
        data = runner.chat_json(node, system, user)
        return schema.model_validate(data)
    except Exception as e:  # noqa: BLE001
        log.warning("节点 %s 降级: %s", node, str(e)[:160])
        return schema.degraded(node, type(e).__name__)


def technical_node(state, runner):
    log.info("[节点] 技术分析师")
    fac = state.get("factors") or {}
    ml = state.get("ml") or {}
    ml_line = (f"\n程序ML集成信号（随机森林，纯本地训练）：{ml.get('signal','—')}；"
               f"主要贡献因子={P.j(ml.get('top_features', []))}。"
               if ml.get("up_prob") is not None else "")
    kr = state.get("kronos") or {}
    kronos_line = (f"\nKronos金融K线基础模型预测：{kr.get('direction','—')}，{kr.get('note','—')}。"
                   if kr.get("up_pct") is not None else "")
    user = (
        f"{P.header(state)}\n\n以下是程序计算好的技术面事实（JSON）：\n{P.j(state['tech'])}\n\n"
        f"以下是程序多因子评分（程序算好的标准化分，-1空~+1多，仅供参考）：\n{P.j(fac)}\n"
        f"{ml_line}{kronos_line}\n\n"
        "请给出技术面信号 JSON：stance(强烈看多/看多/中性/看空/强烈看空)、confidence、"
        "view(120字内)、key_points(数组)、risks(数组)。"
    )
    sig = _run(runner, "technical", P.SYS_TECHNICAL, user, AnalystSignal)
    return {"signals": {**state.get("signals", {}), "technical": sig.model_dump()}}


def fundamental_node(state, runner):
    log.info("[节点] 基本面分析师")
    funda = state.get("funda") or {}
    user = (
        f"{P.header(state)}\n\n以下是程序取得的基本面资料（JSON，字段缺失即数据不足）：\n{P.j(funda)}\n\n"
        "请给出基本面信号 JSON，字段同技术面。加密货币请基于链上/市场结构常识定性，"
        "并明确说明传统估值不适用。"
    )
    sig = _run(runner, "fundamental", P.SYS_FUNDAMENTAL, user, AnalystSignal)
    return {"signals": {**state.get("signals", {}), "fundamental": sig.model_dump()}}


def news_node(state, runner):
    log.info("[节点] 新闻分析师")
    news = state.get("news", [])
    brief = [{"time": n.get("published_at"), "source": n.get("source"),
              "title": n.get("title"), "summary": (n.get("content") or "")[:160]}
             for n in news[:18]]
    user = (
        f"{P.header(state)}\n\n以下是与该标的相关的最新资讯及市场快讯：\n{P.j(brief)}\n\n"
        "请给出新闻面信号 JSON，字段同技术面；没有有效新闻时 stance 取中性并说明。"
    )
    sig = _run(runner, "news", P.SYS_NEWS, user, AnalystSignal)
    return {"signals": {**state.get("signals", {}), "news": sig.model_dump()}}


def sentiment_node(state, runner):
    log.info("[节点] 情绪分析师")
    tech = state["tech"]
    price_behavior = {
        "近1日涨跌%": tech.get("chg_pct_1d"),
        "近5/20/60日涨跌%": tech.get("chg_pct_periods"),
        "60日区间位置%": tech.get("pos_in_60d_pct"),
        "5日/20日量比": tech.get("vol_ratio_5_20"),
    }
    news_titles = [n.get("title", "") for n in state.get("news", [])[:15]]
    sml = state.get("sentiment_ml") or {}
    sml_line = (f"\n本地FinBERT金融情感（{sml.get('n',0)}条标题）：{sml.get('note','—')}"
                f"（{sml.get('counts',{})}）。" if sml.get("n") else "")
    user = (
        f"{P.header(state)}\n近期价格行为：\n{P.j(price_behavior)}\n\n近期新闻标题：\n"
        f"{P.j(news_titles)}{sml_line}\n\n请给出情绪面信号 JSON，字段同技术面。"
    )
    sig = _run(runner, "sentiment", P.SYS_SENTIMENT, user, AnalystSignal)
    return {"signals": {**state.get("signals", {}), "sentiment": sig.model_dump()}}


def bull_node(state, runner):
    log.info("[节点] 多头研究员")
    user = (
        f"{P.header(state)}\n四份分析师报告：\n{P.j(state['signals'])}\n\n"
        "请作为多头研究员，输出 JSON：bull_case(字符串数组，3-5 条最有力的看多理由，"
        "每条需指明依据来自哪份报告)。"
    )
    d = _run(runner, "debate_bull", P.SYS_BULL, user, Debate)
    return {"bull_case": d.bull_case}


def bear_node(state, runner):
    log.info("[节点] 空头研究员")
    user = (
        f"{P.header(state)}\n四份分析师报告：\n{P.j(state['signals'])}\n\n"
        "请作为空头研究员，输出 JSON：bear_case(字符串数组，3-5 条最有力的看空/风险理由，"
        "每条需指明依据来自哪份报告)。"
    )
    d = _run(runner, "debate_bear", P.SYS_BEAR, user, Debate)
    return {"bear_case": d.bear_case}


def trader_node(state, runner):
    log.info("[节点] 交易员")
    price = state["quote"]["price"]
    history = state.get("history") or []
    history_note = (
        f"\n历史决策复盘（同标的，含实际收益）：\n{P.j(history)}\n"
        "若过往决策曾出现方向性错误，请在 reasoning 中说明本次如何避免重蹈。\n"
        if history else "")
    patterns = state.get("patterns") or []
    pattern_note = (
        f"\n历史相似形态检索（近20交易日形态 vs 全历史，含其后10日真实表现）：\n{P.j(patterns)}\n"
        "注意：历史相似不保证未来重演，仅作统计参考。\n"
        if patterns else "")
    user = (
        f"{P.header(state)}\n分析师报告：\n{P.j(state['signals'])}\n\n"
        f"多头理由：{P.j(state.get('bull_case', []))}\n"
        f"空头理由：{P.j(state.get('bear_case', []))}\n"
        f"{history_note}"
        f"{pattern_note}"
        f"技术参考：ATR14={state['tech'].get('atr14')}（占价 "
        f"{state['tech'].get('atr14_pct')}%），布林带={P.j(state['tech'].get('boll'))}\n\n"
        f"当前价严格等于 {price}，止损与目标必须围绕该价格与 ATR 给出，"
        "不得使用任何其他价格。输出 JSON：action(强烈买入/买入/观望/回避/卖出)、"
        "confidence、horizon、entry、position_pct(0-100 整数)、stop_loss(数值或null)、"
        "targets(数值数组，最多3个)、reasoning。"
    )
    plan = _run(runner, "trader", P.SYS_TRADER, user, TraderPlan)
    return {"trader": plan.model_dump()}


def risk_node(state, runner):
    log.info("[节点] 风控/组合经理（终审）")
    market = state["market"]
    # A股个股30%、A股ETF 40%（分散化产品额度更高）、美股/港股25%、全球/加密20%
    if market == "CN" and state.get("security") == "ETF":
        base_cap = 40
    else:
        base_cap = {"CN": 30, "US": 25, "HK": 25, "GLOBAL": 20, "CRYPTO": 20}.get(market, 20)
    # 市场状态路由（二期）：熊市×0.5、震荡×0.75、牛市×1.0
    regime = state.get("regime") or {}
    mult = float(regime.get("position_multiplier") or 1.0)
    cap = int(round(base_cap * mult))
    trader = state["trader"]
    price = state["quote"]["price"]
    risk = None
    # 程序量化综合分（融合多因子+ML+市场状态，确定性参考，非 LLM 观点）
    fac = state.get("factors") or {}
    quant = state.get("quant") or {}
    fac_line = (f"程序量化综合分={quant.get('score')}/100（{quant.get('verdict', '—')}；"
                f"{quant.get('note', '')}），程序依据={P.j(quant.get('basis', []))}；")
    user = (
        f"{P.header(state)}\n交易员提案：\n{P.j(trader)}\n\n"
        f"市场类型={P.MARKET_NAME.get(market, market)}，市场状态={regime.get('regime','?')}"
        f"（{regime.get('note','')}，风险预算系数{mult:.2f}），单标的仓位上限 {cap}%；"
        f"当前价 {price}；ATR14%={state['tech'].get('atr14_pct')}；{fac_line}"
        f"空头理由={P.j(state.get('bear_case', []))}；信号={P.j(state['signals'])}\n\n"
        f"历史决策复盘={P.j(state.get('history') or [])}\n\n"
        f"历史相似形态={P.j(state.get('patterns') or [])}\n\n"
        "请输出 JSON：approved(bool)、adjusted_action、adjusted_position_pct(不超上限)、"
        "stop_loss、targets、scenarios(数组，恰好3项：label=乐观/基准/悲观，"
        "每项含 prob_pct(三者合计100)、price_target、condition)、notes(字符串数组)。"
    )
    risk = _run(runner, "risk", P.SYS_RISK, user, RiskDecision)

    # 组装最终决策
    confidence = trader.get("confidence", 50)
    if not risk.approved:
        confidence = min(confidence, 40)
    reasons = [trader.get("reasoning", "")] + state.get("bull_case", [])[:2]
    risks = state.get("bear_case", []) + risk.notes
    for s in state.get("signals", {}).values():
        risks.extend(s.get("risks", [])[:2])
    # 风险去重保序
    seen, risks_u = set(), []
    for r in risks:
        if r and r not in seen:
            seen.add(r)
            risks_u.append(r)

    final = {
        "ticker": state["ticker"],
        "name": state.get("name") or state["ticker"],
        "market": market,
        "asof": state.get("asof"),
        "price": price,
        "action": risk.adjusted_action,
        "confidence": confidence,
        "position_pct": risk.adjusted_position_pct,
        "stop_loss": risk.stop_loss,
        "targets": risk.targets,
        "horizon": trader.get("horizon", ""),
        "entry": trader.get("entry", ""),
        "scenarios": [s.model_dump() for s in risk.scenarios],
        "summary": "；".join(risk.notes[:3]) if risk.notes else trader.get("reasoning", ""),
        "reasons": [r for r in reasons if r],
        "risks": risks_u[:8],
    }
    return {"risk": risk.model_dump(exclude_none=True), "final": final,
            "tokens": runner.usage()}


def bind(runner):
    """把 runner 注入所有节点，返回 (name, callable) 列表。"""
    pairs = [
        ("technical", technical_node), ("fundamental", fundamental_node),
        ("news", news_node), ("sentiment", sentiment_node),
        ("bull", bull_node), ("bear", bear_node),
        ("trader", trader_node), ("risk", risk_node),
    ]
    return [(name, partial(fn, runner=runner)) for name, fn in pairs]
