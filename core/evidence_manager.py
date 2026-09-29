# -*- coding: utf-8 -*-
"""数据溯源与证据链（模块八）。

每次 AI 分析把"程序事实（数据快照）"与结论关联登记，形成可审计证据链：
- register_claim：登记单条结论与其数据来源
- save_report_evidence：从一次完整分析状态批量登记（signals/final/quote 等程序事实）
- get_evidence：按 analysis_id 取回证据链

设计参考 FinRobot RAG：结论必须可回看原始数据，杜绝"黑盒结论"。
"""
from __future__ import annotations

import json
import logging
import time
from typing import List, Optional

from core.data.cache import get_conn

log = logging.getLogger("stockai.evidence")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS evidence(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  analysis_id TEXT,
  claim_index INTEGER,
  claim TEXT,
  source TEXT,
  data_snapshot TEXT,
  created_at REAL
);
CREATE INDEX IF NOT EXISTS idx_evidence_aid ON evidence(analysis_id);
"""


def init() -> None:
    with get_conn() as conn:
        conn.executescript(_SCHEMA)


def register_claim(analysis_id: str, claim_index: int, claim: str,
                   source: str, data_snapshot: dict) -> None:
    """登记一条结论与其数据来源快照（source 如 'RSI(14)' / '近20日数据' / '新闻管道'）。"""
    init()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO evidence(analysis_id, claim_index, claim, source, data_snapshot, created_at)"
            " VALUES (?,?,?,?,?,?)",
            (analysis_id, claim_index, claim, source,
             json.dumps(data_snapshot, ensure_ascii=False, default=str), time.time()))


def save_report_evidence(analysis_id: str, state: dict) -> int:
    """从一次完整分析状态批量登记程序事实为证据（幂等：先清后写）。"""
    if not state:
        return 0
    init()
    quote = state.get("quote") or {}
    tech = state.get("tech") or {}
    signals = state.get("signals") or {}
    final = state.get("final") or {}
    trader = state.get("trader") or {}
    risk = state.get("risk") or {}

    rows: list[tuple] = []
    idx = 0

    # 行情快照（程序事实）
    rows.append((analysis_id, idx, f"行情快照：{state.get('ticker')}",
                 "行情数据", {"quote": quote, "asof": state.get("asof", "")}))
    idx += 1

    # 技术指标（程序计算）
    if tech:
        rows.append((analysis_id, idx, "技术指标快照（程序计算）",
                     "core.quant.indicators", {"tech": tech}))
        idx += 1

    # 多因子评分 / ML / Kronos
    for key, label in (("factors", "多因子评分（程序计算）"),
                       ("ml", "本地随机森林ML信号"),
                       ("kronos", "Kronos金融K线基础模型")):
        v = state.get(key)
        if v:
            rows.append((analysis_id, idx, label, "本地模型", {key: v}))
            idx += 1

    # 新闻（时间+来源+标题）
    news = state.get("news") or []
    if news:
        brief = [{"time": n.get("published_at"), "source": n.get("source"),
                  "title": n.get("title")} for n in news[:18]]
        rows.append((analysis_id, idx, f"相关资讯 {len(news)} 条", "新闻管道", {"news": brief}))
        idx += 1

    # 各分析师结论（引用上面的事实）
    for k, label in (("technical", "技术分析师信号"), ("fundamental", "基本面分析师信号"),
                     ("news", "新闻分析师信号"), ("sentiment", "情绪分析师信号")):
        v = signals.get(k)
        if v:
            rows.append((analysis_id, idx, f"{label}（{v.get('stance', '—')}）",
                         "核心agents.nodes", {"signal": v}))
            idx += 1

    # 多空论点（自带算式/数据引用）
    for k, label in (("bull_case", "多头论点"), ("bear_case", "空头论点")):
        v = state.get(k)
        if v:
            rows.append((analysis_id, idx, label, "多空辩论", {k: v}))
            idx += 1

    # 交易计划 / 风控 / 最终结论
    if trader:
        rows.append((analysis_id, idx, "交易员计划", "核心agents.trader_node", {"trader": trader}))
        idx += 1
    if risk:
        rows.append((analysis_id, idx, "风控审查", "risk_control_agent", {"risk": risk}))
        idx += 1
    # 风险评估师（确定性统计）与首席分析师 Leader 汇总（模块十）
    ra = state.get("risk_assess")
    if ra:
        rows.append((analysis_id, idx, f"风险评估师：{ra.get('risk_level', '—')}",
                     "core.agents.risk_assessor", {"risk_assess": ra}))
        idx += 1
    leader = final.get("leader")
    if leader:
        rows.append((analysis_id, idx, "首席分析师汇总（一致性审查）",
                     "核心agents.leader_node", {"leader": leader}))
        idx += 1
    if final:
        rows.append((analysis_id, idx, f"最终结论：{final.get('action', '—')}",
                     "核心agents", {"final": final}))
        idx += 1

    with get_conn() as conn:
        conn.execute("DELETE FROM evidence WHERE analysis_id=?", (analysis_id,))
        conn.executemany(
            "INSERT INTO evidence(analysis_id, claim_index, claim, source, data_snapshot, created_at)"
            " VALUES (?,?,?,?,?,?)",
            [(r[0], r[1], r[2], r[3], json.dumps(r[4], ensure_ascii=False, default=str),
              time.time()) for r in rows])
    return len(rows)


def get_evidence(analysis_id: str) -> List[dict]:
    """按 analysis_id 返回完整证据链（按 claim_index 排序）。"""
    init()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT claim_index, claim, source, data_snapshot, created_at"
            " FROM evidence WHERE analysis_id=? ORDER BY claim_index", (analysis_id,)).fetchall()
    return [{"claim_index": r[0], "claim": r[1], "source": r[2],
             "data_snapshot": json.loads(r[3]), "created_at": r[4]} for r in rows]
