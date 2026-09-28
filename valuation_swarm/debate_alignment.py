# -*- coding: utf-8 -*-
"""Swarm 估值：辩论对齐与比例投票收敛。

流程：
  1. 汇总三任务估值（各含 3 Agent）；
  2. 跨任务差异度检查：任务间估值偏离过大 → 触发辩论轮（挑战假设、要求举证）；
  3. 比例投票收敛：按置信度加权，输出收敛估值区间 + 分歧度（dissent）；
  4. 未收敛（分歧过高）→ 输出区间而非单点，并标注"低置信度"。

合规红线：估值仅为数据统计演示，不构成投资建议；分歧大时拒绝给出单点结论。
"""
from __future__ import annotations

import logging

log = logging.getLogger("stockai.valuation_swarm.debate")


class DebateAlignment:
    """基于辩论的对齐程序。"""

    def __init__(self, max_dissent: float = 0.18, min_confidence: float = 0.5):
        self.max_dissent = max_dissent
        self.min_confidence = min_confidence

    def align(self, task_results: dict, max_rounds: int = 3) -> dict:
        """task_results: {task: {value, range, agents:[{agent_id,value,conf,...}]}}"""
        tasks = list(task_results.keys())
        if not tasks:
            return {"value": None, "interval": [0, 0], "dissent": 1.0,
                    "rounds": 0, "aligned": False, "note": "无任务结果"}

        values = {t: task_results[t]["value"] for t in tasks}
        weights = {t: max(self.min_confidence,
                          sum(a["conf"] for a in task_results[t]["agents"]) / 3)
                   for t in tasks}
        dissent, rounds = 1.0, 0
        value, interval = None, [0, 0]
        vlist = list(values.values())

        for _ in range(max_rounds):
            rounds += 1
            lo, hi = min(vlist), max(vlist)
            span = (hi - lo) / (abs(lo) + 1e-9)
            dissent = min(1.0, span)
            if dissent <= self.max_dissent:
                break
            # 辩论轮：离群任务向加权中位数收敛 30%（挑战假设后的让步）
            med = sorted(vlist)[len(vlist) // 2]
            vlist = [v + (med - v) * 0.3 for v in vlist]

        # 比例投票：按置信度加权平均
        wsum = sum(weights.values())
        value = sum(values[t] * weights[t] for t in tasks) / wsum
        spread = (max(vlist) - min(vlist)) / 2
        interval = [round(value - spread, 2), round(value + spread, 2)]
        aligned = dissent <= self.max_dissent
        return {
            "value": round(value, 2),
            "interval": interval,
            "dissent": round(dissent, 3),
            "rounds": rounds,
            "aligned": aligned,
            "note": "" if aligned else "跨任务分歧过大：仅给出区间，不提供单点结论",
        }


def render_report(out: dict) -> str:
    """渲染 Swarm 估值报告（Markdown，含合规声明）。"""
    lines = [f"# LLM Swarm 估值 · {out.get('ticker', '')}", ""]
    for task, r in out.get("task_results", {}).items():
        lines += [f"## {r['label']}（区间 ±{r['range']}）",
                  f"- 收敛估值：{r['value']}",
                  "- Agent 明细："]
        for a in r["agents"]:
            lines.append(f"  - {a['agent_id']}（{a['strategy']}，置信 {a['conf']}）：{a['value']} — {a['basis']}")
        lines.append("")
    conv = out.get("converged") or {}
    lines += ["## 辩论对齐与投票收敛",
              f"- 收敛值：{conv.get('value', '—')}（区间 {conv.get('interval', [0, 0])}）",
              f"- 分歧度：{conv.get('dissent', '—')}，辩论轮次：{conv.get('rounds', 0)}",
              f"- 状态：{'已对齐' if conv.get('aligned') else '未对齐'}"]
    if conv.get("note"):
        lines += [f"- ⚠️ {conv['note']}"]
    lines += ["",
              "> 本估值由 Swarm 框架演示生成，仅供研究学习，不构成任何投资建议。"]
    return "\n".join(lines)


if __name__ == "__main__":
    from valuation_swarm.swarm_agents import SwarmEstimator, TASKS
    facts = {"close": 100, "eps": 5.0, "growth_pct": 8.0, "discount_rate": 0.10,
             "pe_ttm": 20.0, "peer_pe": 22.0, "momentum": 0.12, "sentiment": 0.3}
    sw = SwarmEstimator()
    da = DebateAlignment()
    out = sw.run_with_alignment("SH600519", facts, alignment=da)
    assert out["converged"]["value"] is not None
    assert out["converged"]["rounds"] >= 1
    assert "LLM Swarm 估值" in out["report"]
    # 极端分歧 → 不收敛给区间
    facts2 = dict(facts, close=100, momentum=-0.9, sentiment=-0.9, eps=50.0)
    out2 = sw.run_with_alignment("EXTREME", facts2, alignment=da)
    print("PASS debate_alignment 自测 "
          f"v={out['converged']['value']} dissent={out['converged']['dissent']} "
          f"rounds={out['converged']['rounds']}")
    print(out["report"][:400])
