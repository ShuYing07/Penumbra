# -*- coding: utf-8 -*-
"""LLM Swarm 估值框架。

将估值分解为三个独立金融推理任务（DCF 现金流贴现 / 相对估值 / 情绪动量），
每个任务由三个自主 Agent 完成；每个 Agent 拥有长期记忆（历史估值/结论）与
临时信念（本轮假设），经辩论对齐后按比例投票收敛，提升估值稳定性。

参考 LLM Swarm 论文做法：
- 任务解耦：三个任务互不干扰，可并行/可降级；
- Agent 记忆：长期记忆存估值历史，临时信念本轮可变；
- 辩论收敛：挑战假设 → 比例投票，而非简单平均。
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

log = logging.getLogger("stockai.valuation_swarm")

# 三个估值任务
TASKS = ("dcf", "relative", "sentiment")

_TASK_LABEL = {
    "dcf": "DCF 现金流贴现",
    "relative": "相对估值（可比公司）",
    "sentiment": "情绪与动量",
}


@dataclass
class SwarmAgent:
    """单个估值 Agent：长期记忆 + 临时信念。"""
    agent_id: str
    task: str
    strategy: str = "mid"            # aggressive / mid / conservative
    memory: list = field(default_factory=list)   # 长期记忆（历史估值结论）
    belief: dict = field(default_factory=dict)   # 临时信念（本轮）

    def remember(self, entry: dict) -> None:
        self.memory.append(entry)
        if len(self.memory) > 30:
            self.memory = self.memory[-30:]

    def prior_bias(self) -> float:
        """长期记忆带来的先验：最近 5 条估值的中位数相对 1.0 的偏移。"""
        if not self.memory:
            return 0.0
        recent = [m.get("value_ratio", 1.0) for m in self.memory[-5:]]
        return float(sorted(recent)[len(recent) // 2] - 1.0)

    def confidence(self) -> float:
        """置信度：基于策略与信念一致性。"""
        base = {"aggressive": 0.55, "mid": 0.7, "conservative": 0.85}[self.strategy]
        b = self.belief
        if b.get("signal_strength") is not None:
            base = base * (0.8 + 0.4 * min(1.0, abs(b["signal_strength"])))
        return round(min(0.99, base), 3)


class SwarmEstimator:
    """Swarm 估值编排器。

    estimate(ticker, facts) → 各任务估值结果；
    run_with_alignment(ticker, facts, alignment) → 含辩论对齐收敛结果与报告。
    """

    def __init__(self, agents_per_task: int = 3):
        self.agents: dict[str, list[SwarmAgent]] = {}
        strategies = ("aggressive", "mid", "conservative")
        for task in TASKS:
            self.agents[task] = [
                SwarmAgent(f"{task}-{s}", task, strategy=s)
                for s in strategies[:agents_per_task]
            ]

    # ---------- 三个子任务 ----------
    def _dcf_value(self, facts: dict, bias: float) -> dict:
        eps = facts.get("eps") or 1.0
        growth = facts.get("growth_pct") or 5.0
        disc = facts.get("discount_rate") or 0.10
        years = 5
        cf = eps * (1 + growth / 100) ** years
        value = cf / disc * (1 - 1 / (1 + disc) ** 5) + eps * 4  # 简化贴现+残值
        value = value * (1 + bias)
        return {"value": round(value, 2), "range": round(value * 0.15, 2),
                "basis": f"EPS={eps} g={growth}% r={disc*100:.0f}%"}

    def _relative_value(self, facts: dict, bias: float) -> dict:
        pe = facts.get("pe_ttm") or 20.0
        peer_pe = facts.get("peer_pe") or pe
        eps = facts.get("eps") or 1.0
        value = eps * (pe + peer_pe) / 2 * (1 + bias)
        return {"value": round(value, 2), "range": round(value * 0.12, 2),
                "basis": f"PE={pe} peerPE={peer_pe} EPS={eps}"}

    def _sentiment_value(self, facts: dict, bias: float) -> dict:
        momentum = facts.get("momentum") or 0.0       # 20日动量
        sentiment = facts.get("sentiment") or 0.0     # -1~1 舆情
        base = facts.get("close") or 100.0
        strength = 0.5 * momentum + 0.5 * sentiment
        value = base * (1 + strength) * (1 + bias)
        return {"value": round(value, 2), "range": round(value * 0.2, 2),
                "basis": f"动量={momentum:.2f} 舆情={sentiment:+.2f}",
                "signal_strength": strength}

    def _run_task(self, task: str, facts: dict) -> dict:
        """任务内并行跑 3 个 Agent（策略偏移不同），保留各自估值。"""
        results = []
        for agent in self.agents[task]:
            bias = agent.prior_bias()
            if task == "dcf":
                r = self._dcf_value(facts, bias)
            elif task == "relative":
                r = self._relative_value(facts, bias)
            else:
                r = self._sentiment_value(facts, bias)
            agent.belief = r
            conf = agent.confidence()
            results.append({"agent_id": agent.agent_id, "value": r["value"],
                            "conf": conf, "basis": r["basis"], "strategy": agent.strategy})
            agent.remember({"value_ratio": r["value"] / (facts.get("close") or 1),
                            "ts": time.time()})
        values = [x["value"] for x in results]
        lo, hi = min(values), max(values)
        return {"task": task, "label": _TASK_LABEL[task],
                "value": round(sum(values) / len(values), 2),
                "range": round((hi - lo) / 2, 2), "agents": results}

    # ---------- 主流程 ----------
    def estimate(self, ticker: str, facts: dict | None = None) -> dict:
        facts = dict(facts or {})
        if not facts.get("close"):
            facts["close"] = 100.0  # 缺省基准，避免除零
        task_results = {t: self._run_task(t, facts) for t in TASKS}
        return {
            "ticker": ticker,
            "task_results": task_results,
            "converged": {"value": None, "interval": [0, 0], "dissent": 1.0,
                          "rounds": 0, "aligned": False},
            "report": "",
        }

    def run_with_alignment(self, ticker: str, facts: dict | None = None,
                           alignment=None, max_rounds: int = 3) -> dict:
        """estimate + 辩论对齐（debate_alignment 提供）。"""
        out = self.estimate(ticker, facts)
        if alignment is not None:
            out["converged"] = alignment.align(out["task_results"], max_rounds=max_rounds)
        from valuation_swarm.debate_alignment import render_report
        out["report"] = render_report(out)
        return out


if __name__ == "__main__":
    facts = {"close": 100, "eps": 5.0, "growth_pct": 8.0, "discount_rate": 0.10,
             "pe_ttm": 20.0, "peer_pe": 22.0, "momentum": 0.12, "sentiment": 0.3}
    sw = SwarmEstimator()
    out = sw.estimate("SH600519", facts)
    assert set(out["task_results"]) == set(TASKS)
    for t in TASKS:
        assert len(out["task_results"][t]["agents"]) == 3
    # 长期记忆生效：再次估值应产生先验偏置
    sw.estimate("SH600519", facts)
    assert all(len(a.memory) >= 2 for ag in sw.agents.values() for a in ag)
    print("PASS swarm_agents 自测（3 任务 x 3 Agent，记忆累积）")
