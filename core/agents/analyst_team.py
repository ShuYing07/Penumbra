# -*- coding: utf-8 -*-
"""多智能体投研团队（任务书B·模块一）。

参考 FinSight 7-Agent 并行执行组与 TradingAgents 层级编排：

- 7 名专业分析师：技术 / 基本面 / 新闻 / 情绪（数据组，并行）；
  宏观 / 风险 / 深度研究（综合组，在数据组完成后并行）。
- 并行执行：asyncio.gather + 线程池（LLM 调用为同步阻塞，用 to_thread 包装）。
- 层级编排：数据组 → 综合组 → 多头/空头辩论 → 首席分析师 → 投资组合经理
  （批准/拒绝交易提案，含风控否决权）。
- 共享上下文：每次团队分析的完整结果写入 analysis_context.json（DATA_DIR 下，
  按 ticker+时间戳命名，后续 Agent/研究笔记可读取）。

全部输出为研究性信息，不构成投资建议。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Dict, List, Optional

from core.agents import nodes
from core.agents.graph import gather_facts
from core.config import DATA_DIR

log = logging.getLogger("stockai.agents.team")

# ---------------------------------------------------------------------------
# 分析师注册表（供 execution_console 瀑布图 / 并行组调度 / UI 展示使用）
# ---------------------------------------------------------------------------
ANALYST_DEFS: List[Dict[str, object]] = [
    {"key": "technical", "name": "技术分析师", "group": "data",
     "tools": ["指标计算", "形态识别", "K线数据"]},
    {"key": "fundamental", "name": "基本面分析师", "group": "data",
     "tools": ["财报数据", "估值模型", "同行对比"]},
    {"key": "news", "name": "新闻分析师", "group": "data",
     "tools": ["新闻管道", "事件抽取"]},
    {"key": "sentiment", "name": "情绪分析师", "group": "data",
     "tools": ["情感分析", "舆情监控"]},
    {"key": "macro", "name": "宏观分析师", "group": "synthesis",
     "tools": ["宏观数据", "政策追踪"]},
    {"key": "risk_assessor", "name": "风险评估师", "group": "synthesis",
     "tools": ["波动率计算", "VaR模型", "压力测试"]},
    {"key": "deep_researcher", "name": "深度研究员", "group": "synthesis",
     "tools": ["全工具集", "跨维度推理"]},
]

_DATA_KEYS = ["technical", "fundamental", "news", "sentiment"]
_SYNTH_KEYS = ["macro", "risk_assess", "deep_research"]


def analyst_meta(key: str) -> Dict[str, object]:
    for a in ANALYST_DEFS:
        if a["key"] == key:
            return a
    return {}


# ---------------------------------------------------------------------------
# 宏观分析师（确定性规则，基于市场状态 regime，可选 LLM 增强）
# ---------------------------------------------------------------------------
def macro_analyst(state: Dict[str, object]) -> Dict[str, object]:
    """宏观信号：基于程序采集的市场状态（regime）做确定性判断。

    不依赖 LLM，保证离线可测；regime 缺失时输出 data-insufficient 标注。
    """
    regime = state.get("regime") or {}
    out: Dict[str, object] = {"source": "rule"}
    if not regime:
        out.update({"stance": "中性", "confidence": 0.2,
                    "view": "宏观状态数据不足，无法评估（数据不足，不构成判断）",
                    "key_points": [], "risks": []})
        return out
    mkt = str(regime.get("market", ""))
    trend = str(regime.get("trend", ""))
    vol = str(regime.get("volatility", ""))
    stance = "中性"
    conf = 0.5
    if "涨" in mkt or "牛" in trend:
        stance, conf = "看多", 0.6
    elif "跌" in mkt or "熊" in trend:
        stance, conf = "看空", 0.6
    if "高" in vol:
        stance = "看空" if stance == "看多" else ("看空" if stance == "中性" else stance)
        conf = min(conf + 0.15, 0.9)
    out.update({
        "stance": stance,
        "confidence": round(conf, 2),
        "view": f"当前市场状态：{mkt or '—'}；趋势：{trend or '—'}；波动：{vol or '—'}。"
                f"宏观层给出{stance}倾向（规则判定，供参考）。",
        "key_points": [f"regime.market={mkt}", f"regime.trend={trend}",
                       f"regime.volatility={vol}"],
        "risks": ["宏观判断为规则近似，未接入利率/通胀实时数据"] if vol == "高" else [],
    })
    return out


# ---------------------------------------------------------------------------
# 深度研究员（跨维度综合推理，规则加权 + 一致性检查）
# ---------------------------------------------------------------------------
def deep_researcher(state: Dict[str, object]) -> Dict[str, object]:
    """跨维度综合：对全部分析师信号做加权汇总与一致性检查。"""
    signals = state.get("signals") or {}
    weights = {"technical": 0.25, "fundamental": 0.25, "news": 0.15,
               "sentiment": 0.15, "macro": 0.10, "risk_assess": 0.05}
    score_map = {"强烈看多": 2, "看多": 1, "中性": 0, "看空": -1, "强烈看空": -2}
    total, wsum = 0.0, 0.0
    detail: Dict[str, object] = {}
    for k, w in weights.items():
        sig = signals.get(k) or {}
        st = str(sig.get("stance", ""))
        conf = float(sig.get("confidence", 0.5) or 0.5)
        if st in score_map:
            total += score_map[st] * conf * w
            wsum += conf * w
            detail[k] = f"{st}(conf={conf:.2f})"
    score = (total / wsum) if wsum > 0 else 0.0
    stance = ("强烈看多" if score > 1.2 else "看多" if score > 0.4 else
              "看空" if score < -0.4 else "强烈看空" if score < -1.2 else "中性")
    # 一致性检查：方向相反且置信度都高 → 提示分歧
    bulls = sum(1 for k in ("technical", "fundamental", "news", "sentiment")
                if str((signals.get(k) or {}).get("stance", "")).startswith("看多"))
    bears = sum(1 for k in ("technical", "fundamental", "news", "sentiment")
                if str((signals.get(k) or {}).get("stance", "")).startswith("看空"))
    note = ""
    if bulls >= 2 and bears >= 2:
        note = "⚠️ 分析师观点明显分歧（多空各≥2），建议谨慎、等待进一步信号收敛"
    return {
        "stance": stance,
        "score": round(score, 3),
        "detail": detail,
        "divergence": note,
        "view": f"综合 {len(detail)} 个维度信号，倾向「{stance}」（综合分 {score:.2f}）。{note}",
        "key_points": list(detail.values()),
        "risks": ["综合结论依赖各分析师信号质量，需结合证据链交叉验证"],
    }


# ---------------------------------------------------------------------------
# 并行执行组
# ---------------------------------------------------------------------------
def _apply_signal(state: Dict[str, object], key: str, out: Dict[str, object]) -> Dict[str, object]:
    state.setdefault("signals", {})
    state["signals"][key] = out
    return state


def _run_data_member(key: str, state: Dict[str, object], runner) -> Dict[str, object]:
    """执行一个数据组成员（technical/fundamental/news/sentiment）。"""
    fn = {"technical": nodes.technical_node, "fundamental": nodes.fundamental_node,
          "news": nodes.news_node, "sentiment": nodes.sentiment_node}.get(key)
    if not fn:
        return {"signals": {**state.get("signals", {}), key: {
            "stance": "中性", "confidence": 0.2, "view": "未知分析师", "key_points": [], "risks": []}}}
    return fn(state, runner)


def run_data_group(state: Dict[str, object], runner, max_workers: int = 4) -> Dict[str, object]:
    """数据组并行执行（线程池）。返回更新后的 state。"""
    with ThreadPoolExecutor(max_workers=min(max_workers, len(_DATA_KEYS))) as ex:
        futures = {ex.submit(_run_data_member, k, dict(state), runner): k
                   for k in _DATA_KEYS}
        for fut in futures:
            key = futures[fut]
            try:
                delta = fut.result()
                state["signals"].update(delta.get("signals", {}))
            except Exception as e:  # noqa: BLE001
                log.warning("数据组 %s 失败: %s", key, e)
    return state


def run_synthesis_group(state: Dict[str, object], runner) -> Dict[str, object]:
    """综合组并行执行：宏观（规则）+ 风险评估师（确定性）+ 深度研究（规则）。"""
    def _risk() -> Dict[str, object]:
        try:
            from core.agents.risk_assessor import assess_risk
            bars = state.get("bars")
            if bars is None:
                from core.data.service import get_daily
                bars, _ = get_daily(state.get("ticker", ""), use_cache=True)
            r = assess_risk(bars)
            r["stance"] = "看空" if r.get("risk_level") == "高" else "中性"
            r["confidence"] = 0.7
            r["key_points"] = [f"年化波动 {r.get('vol_annual_pct')}%",
                               f"95%VaR {r.get('var95_pct')}%",
                               f"最大回撤 {r.get('max_drawdown_pct')}%"]
            r["risks"] = [f"压力测试：{r.get('stress', '—')}"]
            return r
        except Exception as e:  # noqa: BLE001
            return {"stance": "中性", "confidence": 0.2,
                    "view": f"风险评估不可用: {e}", "key_points": [], "risks": []}

    with ThreadPoolExecutor(max_workers=3) as ex:
        f_macro = ex.submit(macro_analyst, dict(state))
        f_risk = ex.submit(_risk)
        f_deep = ex.submit(deep_researcher, dict(state))
        state["signals"]["macro"] = f_macro.result()
        state["signals"]["risk_assess"] = f_risk.result()
        state["signals"]["deep_research"] = f_deep.result()
    return state


# ---------------------------------------------------------------------------
# 投资组合经理（批准/拒绝交易提案，含风控否决权）
# ---------------------------------------------------------------------------
class InvestmentManager:
    """组合经理：审查首席分析师结论与风控结果，给出批准/拒绝/条件通过。"""

    def __init__(self, max_position: float = 0.20, min_score: float = 0.3):
        self.max_position = max_position
        self.min_score = min_score

    def review(self, state: Dict[str, object]) -> Dict[str, object]:
        signals = state.get("signals") or {}
        risk = signals.get("risk_assess") or {}
        final = state.get("final") or {}
        leader = state.get("leader") or final.get("leader") or {}
        consensus = str(leader.get("consensus") or final.get("consensus") or "中性")
        risk_level = str(risk.get("risk_level") or "")
        var95 = float(risk.get("var95_pct") or 0.0)
        vol = float(risk.get("vol_annual_pct") or 0.0)

        reasons: List[str] = []
        # 风控否决权
        if risk_level == "高":
            reasons.append("风险评估师：风险等级=高（否决）")
            return self._decide("rejected", 0.0, reasons, "风控否决：风险等级为高")
        if var95 >= 8.0:
            reasons.append(f"95%VaR={var95}% 超阈值（否决）")
            return self._decide("rejected", 0.0, reasons, "风控否决：VaR超阈值")
        # 共识方向
        if consensus in ("强烈看多", "看多"):
            pos = min(self.max_position, round(10.0 / vol, 2)) if vol > 0 else self.max_position
            reasons.append(f"首席共识={consensus}，VaR={var95}% 可接受")
            return self._decide("approved", max(0.0, min(pos, self.max_position)),
                                reasons, "批准")
        if consensus in ("强烈看空", "看空"):
            reasons.append(f"首席共识={consensus}，不持仓")
            return self._decide("rejected", 0.0, reasons, "空头共识不建仓")
        reasons.append(f"首席共识={consensus}（中性/分歧），建议观察")
        return self._decide("conditional", 0.0, reasons, "条件通过：仅观察，不建仓")

    @staticmethod
    def _decide(decision: str, position: float, reasons: List[str], summary: str) -> Dict[str, object]:
        return {
            "decision": decision,
            "max_position": round(position, 4),
            "reasons": reasons,
            "summary": summary,
            "engine": "rule",
        }


# ---------------------------------------------------------------------------
# 全流程入口（asyncio.gather 并行 + 同步兼容）
# ---------------------------------------------------------------------------
def save_analysis_context(ticker: str, state: Dict[str, object]) -> str:
    """把团队分析结果写入 analysis_context.json（按 ticker+时间戳命名）。"""
    os.makedirs(DATA_DIR, exist_ok=True)
    path = os.path.join(
        DATA_DIR, f"analysis_context_{ticker}_{time.strftime('%Y%m%d_%H%M%S')}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, default=str, indent=2)
    return path


async def run_analysis_team_async(ticker: str, runner=None,
                                  as_of: Optional[str] = None,
                                  progress_cb: Optional[Callable] = None) -> Dict[str, object]:
    """异步全流程：采集事实 → 数据组并行 → 综合组并行 → 辩论 → 首席 → 组合经理。"""
    from core.agents.graph import LLMRunner
    from core.agents import graph as G

    runner = runner or LLMRunner()
    if progress_cb:
        progress_cb("采集事实…")
    state = gather_facts(ticker, as_of=as_of)
    state.setdefault("signals", {})

    def _cb(txt):  # 并行组内进度
        if progress_cb:
            progress_cb(txt)

    _cb("数据组并行分析（技术/基本面/新闻/情绪）…")
    await asyncio.get_event_loop().run_in_executor(
        None, run_data_group, state, runner)

    _cb("综合组并行分析（宏观/风险/深度研究）…")
    await asyncio.get_event_loop().run_in_executor(
        None, run_synthesis_group, state, runner)

    _cb("多头/空头辩论…")
    for key in ("bull", "bear"):
        delta = {"bull": nodes.bull_node, "bear": nodes.bear_node}[key](state, runner)
        if key == "bull":
            state["bull_case"] = delta.get("bull_case") or []
        else:
            state["bear_case"] = delta.get("bear_case") or []

    _cb("首席分析师汇总…")
    state.update(nodes.leader_node(state, runner))

    _cb("组合经理审查…")
    state["investment"] = InvestmentManager().review(state)

    ctx = save_analysis_context(ticker, state)
    state["context_file"] = os.path.basename(ctx)
    return state


def run_analysis_team(ticker: str, runner=None, as_of: Optional[str] = None,
                      progress_cb: Optional[Callable] = None) -> Dict[str, object]:
    """同步入口（UI 后台线程 / 测试用）：内部用事件循环跑 async 流程。"""
    try:
        return asyncio.run(run_analysis_team_async(ticker, runner, as_of, progress_cb))
    except RuntimeError:
        # 已在事件循环中（如 Jupyter/某些UI）：改用线程执行
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(
                run_analysis_team_async(ticker, runner, as_of, progress_cb))
        finally:
            loop.close()
