# -*- coding: utf-8 -*-
"""策略自进化闭环：预测→批判→反思→进化。

定期复盘历史判断，找出哪些逻辑在什么市场环境下更有效，
自动调整分析提示词中的权重。
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from core.config import now_cn
from core.data.cache import get_conn

log = logging.getLogger("stockai.evo")


@dataclass
class EvolutionReport:
    """一份月度进化报告。"""
    period: str
    total_decisions: int
    evaluated: int
    win_rate: float
    best_regime: str
    worst_regime: str
    lessons: list[str]
    prompt_adjustments: dict


def _ensure_table():
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS evolution_log(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              ts TEXT,
              period TEXT,
              report_json TEXT,
              prompt_weights_json TEXT
            )
        """)


def monthly_review() -> EvolutionReport:
    """月度复盘：分析过去决策的对错，输出经验教训。

    不自动改prompt，只输出建议，用户确认后才生效。
    """
    from core.memory.reflection import decision_stats

    stats = decision_stats()
    total = stats.get("total", 0)
    evaluated = stats.get("evaluated", 0)

    # 按市场环境统计胜率
    regime_stats = {}
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT d.risk_json, d.realized_return_pct, d.action
            FROM decisions d
            WHERE d.evaluated=1 AND d.realized_return_pct IS NOT NULL
        """).fetchall()

    for risk_json, ret, action in rows:
        try:
            risk = json.loads(risk_json) if risk_json else {}
            regime = risk.get("market_regime", "unknown")
        except Exception:
            regime = "unknown"
        if regime not in regime_stats:
            regime_stats[regime] = {"n": 0, "wins": 0, "sum_ret": 0.0}
        regime_stats[regime]["n"] += 1
        regime_stats[regime]["sum_ret"] += ret or 0
        # 方向判断是否正确
        if action in ("买入", "强烈买入") and (ret or 0) > 0:
            regime_stats[regime]["wins"] += 1
        elif action == "卖出" and (ret or 0) < 0:
            regime_stats[regime]["wins"] += 1

    # 找最好/最差的市场环境
    best_regime = "unknown"
    worst_regime = "unknown"
    best_wr = -1.0
    worst_wr = 2.0
    for regime, s in regime_stats.items():
        if s["n"] < 3:
            continue
        wr = s["wins"] / s["n"]
        if wr > best_wr:
            best_wr = wr
            best_regime = regime
        if wr < worst_wr:
            worst_wr = wr
            worst_regime = regime

    # 生成经验教训
    lessons = []
    win_rate_pct = stats.get("win_rate_pct")
    if win_rate_pct is not None:
        if win_rate_pct >= 60:
            lessons.append(f"整体方向胜率{win_rate_pct}%，当前逻辑有效，保持策略")
        elif win_rate_pct >= 50:
            lessons.append(f"整体方向胜率{win_rate_pct}%，略高于随机，需谨慎")
        else:
            lessons.append(f"整体方向胜率仅{win_rate_pct}%，低于随机水平，需重新审视逻辑")

    if best_regime != "unknown":
        lessons.append(f"在「{best_regime}」市场环境下判断最准确，应侧重此类环境分析")
    if worst_regime != "unknown" and worst_regime != best_regime:
        lessons.append(f"在「{worst_regime}」市场环境下判断最差，此类环境应降低置信度")

    # 提示词权重建议（不自动改，只输出建议）
    prompt_adjustments = {}
    if best_regime != "unknown":
        prompt_adjustments["regime_weight"] = {
            best_regime: 1.2,  # 这种环境下多给20%权重
            worst_regime: 0.7,  # 这种环境下少给30%权重
        }

    report = EvolutionReport(
        period=now_cn().strftime("%Y-%m"),
        total_decisions=total,
        evaluated=evaluated,
        win_rate=win_rate_pct or 0.0,
        best_regime=best_regime,
        worst_regime=worst_regime,
        lessons=lessons,
        prompt_adjustments=prompt_adjustments,
    )

    # 落库
    _ensure_table()
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO evolution_log(ts, period, report_json, prompt_weights_json)
               VALUES (?,?,?,?)""",
            (now_cn().isoformat(timespec="seconds"), report.period,
             json.dumps({
                 "total": total, "evaluated": evaluated,
                 "win_rate": report.win_rate, "lessons": lessons,
             }, ensure_ascii=False),
             json.dumps(prompt_adjustments, ensure_ascii=False)))

    return report


def get_evolution_context() -> dict:
    """获取最新的进化结论，注入到分析prompt中。"""
    _ensure_table()
    with get_conn() as conn:
        row = conn.execute(
            """SELECT report_json, prompt_weights_json FROM evolution_log
               ORDER BY id DESC LIMIT 1"""
        ).fetchone()
    if not row:
        return {}
    try:
        return {
            "report": json.loads(row[0]),
            "prompt_weights": json.loads(row[1]),
        }
    except Exception:
        return {}
