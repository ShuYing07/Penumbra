# -*- coding: utf-8 -*-
"""分析管线编排：采集事实 → LangGraph 多智能体 → 最终决策。"""
from __future__ import annotations

import logging
from typing import TypedDict

import pandas as pd

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from core.agents.nodes import bind
from core.config import now_cn
from core.data import cache, service
from core.llm import LLMRunner
from core.quant.indicators import latest_snapshot
from core.quant.factors import compute_factors
from core.quant.market_regime import classify_regime
from core.quant.ml_signal import ml_signal
from core.quant.ensemble import quantitative_score
from core.ml import finbert
from core.ml import kronos_forecast

log = logging.getLogger("stockai.graph")


def _to_native(obj):
    """递归把 numpy 标量/数组转成原生 Python 类型（保证 checkpointer 可序列化）。"""
    import numpy as np

    if isinstance(obj, np.generic):
        return obj.item()
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, dict):
        return {k: _to_native(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_native(v) for v in obj]
    return obj


class AnalysisState(TypedDict, total=False):
    ticker: str
    market: str
    security: str       # STOCK / ETF（A股场内基金）
    name: str
    asof: str
    quote: dict
    tech: dict
    factors: dict
    regime: dict
    ml: dict
    quant: dict
    sentiment_ml: dict
    kronos: dict
    funda: dict
    news: list
    signals: dict
    bull_case: list
    bear_case: list
    trader: dict
    risk: dict
    final: dict
    tokens: dict
    errors: list
    history: list
    patterns: list
    started_at: str


# 节点中文名（UI 进度展示与日志共用）
NODE_LABELS = {
    "technical": "技术分析师", "fundamental": "基本面分析师",
    "news": "新闻分析师", "sentiment": "情绪分析师",
    "bull": "多头研究员", "bear": "空头研究员",
    "trader": "交易员", "risk": "风控终审",
}


def _quote_from_bar(bars) -> dict:
    """用日线末根构造报价（实时不可用/历史回放时点用）。"""
    last, prev = bars["close"].iloc[-1], bars["close"].iloc[-2]
    return {"price": round(float(last), 4), "prev_close": round(float(prev), 4),
            "chg_pct": round((last / prev - 1) * 100, 2),
            "name": "", "date": bars.index[-1].strftime("%Y-%m-%d")}


def _filter_news_asof(news: list, as_of: str) -> list:
    """新闻时点过滤：仅保留 published_at 日期 <= as_of；日期无法解析的保守丢弃（防前视）。"""
    import re

    out = []
    for item in news:
        m = re.match(r"(\d{4}-\d{2}-\d{2})", str(item.get("published_at", "")))
        if m and m.group(1) <= as_of:
            out.append(item)
    return out


def gather_facts(ticker: str, progress_cb=None, as_of: str | None = None) -> AnalysisState:
    """采集事实。as_of 非空时进入历史回放模式：

    - bars 严格截断到 as_of（无前视）；quote 用截断末根 K 线构造（不取实时）；
    - 新闻按 published_at<=as_of best-effort 过滤；反思上下文置空（不看未来反思）；
    - 基本面免费源无历史值，保留当前快照并打 _as_of_note 局限标注。
    """
    def cb(text: str) -> None:
        log.info("%s", text)
        if progress_cb:
            try:
                progress_cb("data", text)
            except Exception:  # noqa: BLE001
                pass

    ticker = ticker.upper()
    market = service.market_of(ticker)
    security = service.security_type(ticker)
    replay = as_of is not None
    cb(f"识别市场 {ticker} → {market}{'（场内ETF）' if security == 'ETF' else ''}"
       f"{'，历史回放时点 ' + as_of if replay else ''}，采集行情…")
    bars, status = service.get_daily(ticker)
    if replay:
        bars = bars[bars.index <= pd.Timestamp(as_of)]
        if len(bars) < 60:
            raise ValueError(f"回放时点 {as_of} 之前日线不足 60 根（实际 {len(bars)}），无法计算指标")
    cb(f"行情 {ticker}：{len(bars)} 根 [{status}]{'（已时点截断）' if replay else ''}")

    if replay:
        quote = _quote_from_bar(bars)
    else:
        try:
            quote = service.get_realtime(ticker)
        except Exception as e:  # noqa: BLE001
            cb(f"实时报价失败 {ticker}：{e}，改用日线末值")
            quote = _quote_from_bar(bars)

    cb("采集基本面资料…")
    funda = service.get_fundamentals(ticker)
    if replay:
        funda = dict(funda)
        funda["_as_of_note"] = f"历史回放({as_of})：免费源无历史基本面，此为当前快照，非时点值"
    cb("采集新闻资讯…")
    news = service.get_news(ticker)
    if replay:
        news = _filter_news_asof(news, as_of)
    cb(f"新闻 {ticker}：{len(news)} 条，开始计算技术指标…")

    tech = latest_snapshot(bars)
    # 多因子评分（一期增强）：程序算好，LLM 只解读
    try:
        factors = compute_factors(bars, funda)
    except Exception as e:  # noqa: BLE001
        log.warning("多因子计算失败：%s", e)
        factors = {"composite": None, "consensus": "因子计算失败", "factors": {}}
    # 市场状态路由（二期）：判别牛/熊/震荡，给仓位调节系数
    try:
        regime = classify_regime(bars)
    except Exception as e:  # noqa: BLE001
        log.warning("市场状态判别失败：%s", e)
        regime = {"regime": "range", "note": "判别失败", "position_multiplier": 0.75}
    # ML 集成信号（三期增强）：随机森林从技术特征学未来5日方向，纯本地
    try:
        ml = ml_signal(bars)
    except Exception as e:  # noqa: BLE001
        log.warning("ML信号失败：%s", e)
        ml = {"up_prob": None, "signal": "不可用", "note": str(e)[:100]}
    # 程序量化综合分（融合多因子+ML+市场状态）
    quant = quantitative_score(factors, ml, regime)
    # FinBERT 本地金融情感（对新闻标题打情感分，零token）
    try:
        titles = [n.get("title", "") for n in (news or [])[:15]]
        sentiment_ml = finbert.sentiment_batch(titles)
    except Exception as e:  # noqa: BLE001
        log.warning("FinBERT情感失败：%s", e)
        sentiment_ml = {"mood": "不可用", "avg_score": 0.0, "n": 0}
    # Kronos 短期K线预测（本地基础模型）
    try:
        kronos = kronos_forecast.forecast(bars)
    except Exception as e:  # noqa: BLE001
        log.warning("Kronos预测失败：%s", e)
        kronos = {"up_pct": None, "direction": "不可用", "note": str(e)[:80]}
    asof = as_of or tech.get("asof") or quote.get("date") or now_cn().strftime("%Y-%m-%d")

    if replay:
        # 回放不注入真实决策反思（那些是时点之后才产生的信息）
        history: list = []
    else:
        # 历史决策反思上下文（三期）：同标的已评估决策注入 prompt
        try:
            from core.memory.reflection import inject_context
            history = inject_context(ticker)
        except Exception as e:  # noqa: BLE001
            log.warning("历史决策上下文加载失败：%s", e)
            history = []

    # 相似历史形态检索（四期）：近20日形态 vs 全历史，含其后真实表现
    # 回放时 bars 已截断，find_similar 自然只能见到 as_of 之前的数据
    try:
        from core.memory.patterns import find_similar
        patterns, _agg = find_similar(bars)
    except Exception as e:  # noqa: BLE001
        log.warning("相似形态检索失败：%s", e)
        patterns = []

    return {
        "ticker": ticker,
        "market": market,
        "security": security,
        "name": quote.get("name") or funda.get("name") or "",
        "asof": asof,
        "quote": quote,
        "tech": tech,
        "factors": factors,
        "regime": regime,
        "ml": ml,
        "quant": quant,
        "sentiment_ml": sentiment_ml,
        "kronos": kronos,
        "funda": funda,
        "news": news,
        "signals": {},
        "errors": [],
        "history": history,
        "patterns": patterns,
        "started_at": now_cn().isoformat(timespec="seconds"),
    }


def build_graph(runner: LLMRunner):
    """串行DAG编排（稳定优先）：
    - START → technical → fundamental → news → sentiment
    - 4分析师完成 → bull → bear → trader → risk → END
    """
    builder = StateGraph(AnalysisState)
    for name, fn in bind(runner):
        builder.add_node(name, fn)

    # 串行执行4个分析师
    builder.add_edge(START, "technical")
    builder.add_edge("technical", "fundamental")
    builder.add_edge("fundamental", "news")
    builder.add_edge("news", "sentiment")

    # 多空辩论
    builder.add_edge("sentiment", "bull")
    builder.add_edge("bull", "bear")

    # trader → risk → END
    builder.add_edge("bear", "trader")
    builder.add_edge("trader", "risk")
    builder.add_edge("risk", END)
    return builder.compile(checkpointer=MemorySaver())


def _delta_degraded(node_key: str, delta: dict) -> bool:
    """判断该节点本次输出是否为降级结果（LLM 调用失败走了默认/桩）。"""
    if node_key in ("technical", "fundamental", "news", "sentiment"):
        sig = (delta.get("signals") or {}).get(node_key) or {}
        return "降级" in str(sig.get("view", "")) or int(sig.get("confidence") or 50) <= 20
    if node_key in ("bull", "bear"):
        vals = (delta.get("bull_case") or []) + (delta.get("bear_case") or [])
        return any("异常" in str(x) for x in vals)
    if node_key == "trader":
        return "异常" in str((delta.get("trader") or {}).get("reasoning", ""))
    if node_key == "risk":
        notes = (delta.get("risk") or {}).get("notes") or []
        return any("异常" in str(x) for x in notes)
    return False


def degraded_nodes(state: dict) -> list[str]:
    """事后扫描完整状态，返回发生降级的节点 key 列表。"""
    bad = []
    for key, sig in (state.get("signals") or {}).items():
        if "降级" in str(sig.get("view", "")) or int(sig.get("confidence") or 50) <= 20:
            bad.append(key)
    if "异常" in str((state.get("trader") or {}).get("reasoning", "")):
        bad.append("trader")
    if any("异常" in str(x) for x in ((state.get("risk") or {}).get("notes") or [])):
        bad.append("risk")
    return bad


def execute_state(state: dict, runner: LLMRunner, progress_cb=None,
                  thread_suffix: str | None = None) -> dict:
    """对已采集的 state 跑 LangGraph 多节点DAG，返回补全 final 的 state（不落库）。

    并行模式：4分析师并行 → 多空并行 → trader → risk。
    额外追踪每个节点的耗时，写入 state["node_timing"]。
    """
    import time
    graph = build_graph(runner)
    suffix = thread_suffix or now_cn().strftime("%Y%m%d%H%M%S")
    thread_id = f"{state['ticker'].upper()}-{suffix}"
    config = {"configurable": {"thread_id": thread_id}}

    node_timing: dict[str, dict] = {}
    result = dict(state)
    if progress_cb is None:
        result = graph.invoke(state, config=config)
    else:
        node_start: dict[str, float] = {}
        for chunk in graph.stream(state, config=config, stream_mode="updates"):
            for node_key, delta in chunk.items():
                if not isinstance(delta, dict) or not delta:
                    continue
                result.update(delta)
                now = time.time()
                if node_key not in node_start:
                    node_start[node_key] = now
                # 节点完成时间 = 当前时间（updates流到即完成）
                elapsed = now - node_start[node_key] if node_key in node_start else 0.0
                if node_key in NODE_LABELS:
                    node_timing[node_key] = {
                        "label": NODE_LABELS[node_key],
                        "elapsed_sec": round(elapsed, 1),
                    }
                    progress_cb("node", (node_key, _delta_degraded(node_key, delta)))

    result["node_timing"] = node_timing
    result["errors"] = degraded_nodes(result)
    return result


def run_analysis(ticker: str, runner: LLMRunner | None = None, progress_cb=None,
                 as_of: str | None = None, persist: bool = True) -> dict:
    """对单个标的跑完整管线，返回 {state, decision_id}。

    progress_cb(kind, payload)：
    - kind="data"：payload=str，数据采集阶段说明；
    - kind="node"：payload=(node_key, degraded)，一个智能体节点完成。

    as_of 非空=历史回放模式（数据时点截断）；persist=False 时不写 decisions 表、
    不入 RAG（回放信号走独立 ai_replay_signals 表，避免污染真实统计）。
    """
    cache.init_db()
    # 冷库首次运行时 decisions 表需先就位，否则反思上下文查询告警
    try:
        from core.memory.decision_log import init as _dl_init

        _dl_init()
    except Exception:  # noqa: BLE001
        pass
    own_runner = runner is None
    runner = runner or LLMRunner()
    runner.meta = {"ticker": ticker}  # 蒸馏语料随节点输出一起记录
    state = _to_native(gather_facts(ticker, progress_cb=progress_cb, as_of=as_of))
    result = execute_state(
        state, runner, progress_cb,
        thread_suffix=f"{as_of}-{now_cn():%H%M%S}" if as_of else None)
    decision_id = None
    if persist and as_of is None:
        decision_id = save_decision(result)
        # 四期：当次分析结论+新闻入学习库（失败不影响主流程）
        try:
            from core.memory.rag import index_analysis
            index_analysis(result)
        except Exception as e:  # noqa: BLE001
            log.warning("学习库入库跳过：%s", e)
    if own_runner:
        log.info("本次分析 token：%s", runner.usage())
    return {"state": result, "decision_id": decision_id}


def save_decision(state: AnalysisState) -> int:
    from core.memory.decision_log import save as save_log

    final = state.get("final") or {}
    return save_log(
        ticker=state["ticker"],
        market=state["market"],
        asof=state.get("asof", ""),
        quote=state.get("quote", {}),
        final=final,
        signals=state.get("signals", {}),
        trader=state.get("trader", {}),
        risk=state.get("risk", {}),
        tokens=state.get("tokens", {}),
    )
