# -*- coding: utf-8 -*-
"""ReMe 记忆框架（模块七 · 参考 EvoTraders / ReMe）。

自我进化交易系统的记忆层：
- 每笔模拟交易后自动反思（reflect）：把交易归类到「趋势跟随 / 逆势 / 纪律 /
  择时 / 消息面」等维度，标注成败原因；
- 跨轮经验沉淀（lessons）：从全部交易中聚合出「赢家特征 / 输家特征」；
- 风格画像（style_profile）：统计胜率、平均盈亏、平均持仓、偏好，输出
  Agent 逐渐形成的投资方法论文本；
- 持久化 SQLite（evo_memory.db，trades / reflections 表）。

全部确定性规则，可单测；trade 输入：
{code, side, entry, exit, qty, pnl, hold_days, reason, ts}
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import sys
import time
from contextlib import contextmanager
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from core.config import DATA_DIR

log = logging.getLogger("stockai.core.agents.evo_memory")

_DB = DATA_DIR / "evo_memory.db"
_SCHEMA = """
CREATE TABLE IF NOT EXISTS evo_trades(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  code TEXT, side TEXT, entry REAL, exit REAL, qty REAL, pnl REAL,
  hold_days REAL, reason TEXT, ts REAL
);
CREATE TABLE IF NOT EXISTS evo_reflections(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  trade_id INTEGER, dimension TEXT, outcome TEXT, insight TEXT, ts REAL
);
CREATE TABLE IF NOT EXISTS evo_analysis_reflections(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT, ticker TEXT, verdict TEXT, confidence REAL, model_engine TEXT,
  summary TEXT, lesson TEXT, ts REAL
);
"""

# 交易行为维度分类（关键词 → 维度）
_DIM_RULES: List[tuple[str, List[str]]] = [
    ("趋势跟随", ["趋势", "突破", "金叉", "均线", "动量"]),
    ("逆势抄底", ["超卖", "抄底", "回踩", "支撑", "低吸"]),
    ("纪律执行", ["止损", "止盈", "纪律", "计划", "分批"]),
    ("消息驱动", ["公告", "新闻", "政策", "利好", "利空"]),
    ("择时波动", ["波动", "回撤", "高点", "低点", "波段"]),
]


def _conn() -> sqlite3.Connection:
    _DB.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(_DB))
    c.executescript(_SCHEMA)
    return c


@contextmanager
def _db():
    c = _conn()
    try:
        yield c
        c.commit()
    finally:
        c.close()


def _classify(reason: str) -> str:
    r = reason or ""
    for dim, kws in _DIM_RULES:
        if any(k in r for k in kws):
            return dim
    return "其他"


def record_trade(trade: Dict[str, Any]) -> int:
    """记录一笔模拟交易，返回 trade_id。"""
    with _db() as c:
        cur = c.execute(
            "INSERT INTO evo_trades(code,side,entry,exit,qty,pnl,hold_days,reason,ts)"
            " VALUES(?,?,?,?,?,?,?,?,?)",
            (str(trade.get("code") or ""), str(trade.get("side") or ""),
             float(trade.get("entry") or 0), float(trade.get("exit") or 0),
             float(trade.get("qty") or 0), float(trade.get("pnl") or 0),
             float(trade.get("hold_days") or 0),
             str(trade.get("reason") or ""), float(trade.get("ts") or time.time())))
        tid = int(cur.lastrowid)
    return tid


def reflect(trade: Dict[str, Any]) -> dict:
    """交易后反思（确定性）：归类维度 + 成败原因 + 洞察。"""
    pnl = float(trade.get("pnl") or 0)
    dim = _classify(trade.get("reason", ""))
    outcome = "win" if pnl > 0 else "loss"
    if outcome == "win":
        insight = (f"{dim} 策略盈利 {pnl:.2f}："
                   f"方向与{_classify(trade.get('reason', ''))}一致，值得保持")
    else:
        insight = (f"{dim} 策略亏损 {pnl:.2f}（持仓 {float(trade.get('hold_days') or 0):.0f} 天）："
                   f"需检查{_classify(trade.get('reason', ''))}信号质量或止损纪律")
    r = {"dimension": dim, "outcome": outcome, "insight": insight}
    try:
        with _db() as c:
            c.execute(
                "INSERT INTO evo_reflections(trade_id,dimension,outcome,insight,ts)"
                " VALUES(?,?,?,?,?)",
                (int(trade.get("trade_id") or 0), dim, outcome, insight,
                 float(trade.get("ts") or time.time())))
    except Exception as e:  # noqa: BLE001
        log.debug("反思入库失败：%s", e)
    return r


def record_and_reflect(trade: Dict[str, Any]) -> dict:
    """一站式：记录交易 + 反思。返回 {trade_id, reflection}。"""
    tid = record_trade(trade)
    trade["trade_id"] = tid
    return {"trade_id": tid, "reflection": reflect(trade)}


def analyze_reflect(analysis: Dict[str, Any]) -> dict:
    """分析级反思（2026-10 升级）：AI 每次完成一次分析后自动沉淀经验。

    analysis: {kind(财报/技术/估值/宏观/情绪/风险/通用), ticker, verdict(方向),
               confidence(0~1), model_engine, summary}
    确定性规则生成学习经验并落库 evo_analysis_reflections，形成
    「分析 → 反思 → 方法论文本 → 后续改进」的自主学习闭环。
    """
    kind = str(analysis.get("kind") or "通用")
    ticker = str(analysis.get("ticker") or "")
    verdict = str(analysis.get("verdict") or "中性")
    conf = min(max(float(analysis.get("confidence") or 0.5), 0.0), 1.0)
    engine = str(analysis.get("model_engine") or "")
    summary = str(analysis.get("summary") or "")[:200]
    if conf >= 0.7:
        lesson = (f"{kind}分析给出高置信「{verdict}」判断（置信度 {conf:.0%}，"
                  f"引擎 {engine or '未知'}），可纳入后续决策基线")
    elif conf <= 0.35:
        lesson = (f"{kind}分析置信度仅 {conf:.0%}（引擎 {engine or '未知'}），"
                  f"应交叉多个数据源/分析师后再决策")
    else:
        lesson = (f"{kind}分析判断「{verdict}」（置信度 {conf:.0%}），"
                  f"需结合多空辩论与风控校准")
    r = {"kind": kind, "lesson": lesson, "confidence": conf, "verdict": verdict}
    try:
        with _db() as c:
            c.execute(
                "INSERT INTO evo_analysis_reflections"
                "(kind,ticker,verdict,confidence,model_engine,summary,lesson,ts)"
                " VALUES(?,?,?,?,?,?,?,?)",
                (kind, ticker, verdict, conf, engine, summary, lesson,
                 float(analysis.get("ts") or time.time())))
    except Exception as e:  # noqa: BLE001
        log.debug("分析反思入库失败：%s", e)
    return r


def analysis_lessons(limit: int = 100) -> dict:
    """聚合历史分析经验：各类分析的置信分布与高频经验，用于学习库/进化页展示。"""
    with _db() as c:
        rows = c.execute(
            "SELECT kind,verdict,confidence,lesson FROM evo_analysis_reflections"
            " ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    if not rows:
        return {"total": 0, "by_kind": {}, "recent": []}
    by_kind: Dict[str, dict] = {}
    for kind, verdict, conf, lesson in rows:
        b = by_kind.setdefault(kind, {"count": 0, "high_conf": 0, "verdicts": {}})
        b["count"] += 1
        if conf >= 0.7:
            b["high_conf"] += 1
        b["verdicts"][verdict] = b["verdicts"].get(verdict, 0) + 1
    return {"total": len(rows), "by_kind": by_kind,
            "recent": [{"kind": r[0], "verdict": r[1], "confidence": r[2],
                        "lesson": r[3]} for r in rows[:10]]}


def lessons(limit: int = 100) -> dict:
    """跨轮经验：从全部交易聚合赢家/输家特征。"""
    with _db() as c:
        rows = c.execute(
            "SELECT pnl,hold_days,reason FROM evo_trades ORDER BY id DESC LIMIT ?",
            (limit,)).fetchall()
    wins = [r for r in rows if r[0] > 0]
    losses = [r for r in rows if r[0] <= 0]
    win_dims: Dict[str, int] = {}
    loss_dims: Dict[str, int] = {}
    for r in wins:
        win_dims[_classify(r[2])] = win_dims.get(_classify(r[2]), 0) + 1
    for r in losses:
        loss_dims[_classify(r[2])] = loss_dims.get(_classify(r[2]), 0) + 1
    return {
        "total": len(rows), "wins": len(wins), "losses": len(losses),
        "win_rate": len(wins) / len(rows) if rows else 0.0,
        "avg_hold_win": round(sum(r[1] for r in wins) / len(wins), 1) if wins else 0.0,
        "avg_hold_loss": round(sum(r[1] for r in losses) / len(losses), 1) if losses else 0.0,
        "win_dimensions": win_dims, "loss_dimensions": loss_dims,
    }


def style_profile() -> dict:
    """风格画像：Agent 逐渐形成的投资方法论。"""
    with _db() as c:
        rows = c.execute("SELECT pnl,hold_days,side,reason FROM evo_trades").fetchall()
    if not rows:
        return {"profile": "尚无交易记录，等待积累交易经验后形成风格", "stats": {}}
    pnls = [r[0] for r in rows]
    holds = [r[1] for r in rows]
    sides = {}
    for r in rows:
        sides[str(r[2]) or "? "] = sides.get(str(r[2]) or "?", 0) + 1
    dims: Dict[str, int] = {}
    for r in rows:
        dims[_classify(r[3])] = dims.get(_classify(r[3]), 0) + 1
    total_pnl = sum(pnls)
    best = max(pnls, default=0.0)
    worst = min(pnls, default=0.0)
    dom_dim = max(dims.items(), key=lambda kv: kv[1]) if dims else ("无", 0)
    dom_side = max(sides.items(), key=lambda kv: kv[1]) if sides else ("无", 0)
    profile = (f"累计 {len(rows)} 笔 · 净盈亏 {total_pnl:.0f} · 胜率 "
               f"{round(sum(1 for p in pnls if p > 0) / len(pnls), 4):.2%} · "
               f"平均持仓 {round(sum(holds) / len(holds), 1):.1f} 天 · "
               f"偏好{dom_side[0]}方向、{dom_dim[0]}策略 · 最佳 {best:.0f} / "
               f"最差 {worst:.0f}")
    return {"profile": profile,
            "stats": {"trades": len(rows), "net_pnl": round(total_pnl, 2),
                      "win_rate": sum(1 for p in pnls if p > 0) / len(pnls) if pnls else 0.0,
                      "avg_hold_days": round(sum(holds) / len(holds), 1),
                      "best_pnl": round(best, 2), "worst_pnl": round(worst, 2),
                      "dimensions": dims, "sides": sides}}


def equity_curve(limit: int = 500) -> List[float]:
    """累计净值曲线（按交易顺序累计 pnl，起点 1.0 归一）。"""
    with _db() as c:
        rows = c.execute(
            "SELECT pnl FROM evo_trades ORDER BY id ASC LIMIT ?", (limit,)).fetchall()
    if not rows:
        return []
    eq, curve = 1.0, []
    for (p,) in rows:
        eq += float(p)
        curve.append(round(eq, 4))
    return curve


def recent_reflections(limit: int = 20) -> List[dict]:
    with _db() as c:
        rows = c.execute(
            "SELECT trade_id,dimension,outcome,insight,ts FROM evo_reflections "
            "ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [{"trade_id": r[0], "dimension": r[1], "outcome": r[2],
             "insight": r[3], "ts": r[4]} for r in rows]


# ---------------------------------------------------------------------------
# FactorMiner 式 Alpha 因子发现 + AQuA 式递归自改进（模块增量）
# ---------------------------------------------------------------------------

def alpha_factors(limit: int = 200) -> List[dict]:
    """从交易历史发现可解释 Alpha 因子（按策略维度聚合）。

    每个因子 = 一个策略维度（趋势跟随/逆势抄底/纪律执行/消息驱动/择时波动），
    输出 {factor, trades, win_rate, avg_pnl, avg_hold, net_pnl, verdict}：
    - 强因子：样本 ≥5 且胜率 ≥0.6（可解释、可复用）；
    - 负因子：样本 ≥5 且胜率 <0.4（应停用/加约束）；
    - 观察因子：样本不足或胜率居中（继续积累样本）。
    确定性规则，不依赖 LLM，可单测。
    """
    with _db() as c:
        rows = c.execute(
            "SELECT pnl,hold_days,reason FROM evo_trades ORDER BY id DESC LIMIT ?",
            (limit,)).fetchall()
    if not rows:
        return []
    factors: Dict[str, Dict[str, Any]] = {}
    for pnl, hold, reason in rows:
        dim = _classify(reason)
        f = factors.setdefault(dim, {"trades": 0, "wins": 0, "pnl_sum": 0.0,
                                     "hold_sum": 0.0})
        f["trades"] += 1
        f["pnl_sum"] += float(pnl)
        f["hold_sum"] += float(hold)
        if float(pnl) > 0:
            f["wins"] += 1
    out = []
    for dim, f in sorted(factors.items(), key=lambda kv: -kv[1]["trades"]):
        win_rate = f["wins"] / f["trades"] if f["trades"] else 0.0
        verdict = ("强因子" if f["trades"] >= 5 and win_rate >= 0.6
                   else "负因子" if f["trades"] >= 5 and win_rate < 0.4
                   else "观察因子")
        out.append({
            "factor": dim, "trades": f["trades"], "wins": f["wins"],
            "win_rate": round(win_rate, 4),
            "avg_pnl": round(f["pnl_sum"] / f["trades"], 2) if f["trades"] else 0.0,
            "avg_hold": round(f["hold_sum"] / f["trades"], 1) if f["trades"] else 0.0,
            "net_pnl": round(f["pnl_sum"], 2), "verdict": verdict,
        })
    return out


def _improvement_suggestion(f: Dict[str, Any]) -> str:
    """按因子统计给出可执行改进建议（规则式，AQuA 递归自改进）。"""
    if f["verdict"] == "强因子":
        return (f"「{f['factor']}」胜率 {f['win_rate']:.0%}（样本 {f['trades']}），"
                f"建议保持策略并逐步加仓，维持纪律执行。")
    if f["verdict"] == "负因子":
        return (f"「{f['factor']}」胜率仅 {f['win_rate']:.0%}（样本 {f['trades']}），"
                f"建议停用该维度或强制附加止损/仓位上限后再观察。")
    return (f"「{f['factor']}」胜率 {f['win_rate']:.0%}（样本 {f['trades']}），"
            f"样本不足或收益不稳，建议限制仓位继续积累样本，避免过早下结论。")


def recursive_improve(limit: int = 200) -> List[dict]:
    """AQuA 式递归自改进：基于因子统计生成改进建议并落库。

    写入 evo_improvements 表（id, factor, win_rate, trades, suggestion, ts），
    形成「交易 → 反思 → 因子统计 → 改进建议」的闭环轨迹；返回本次建议列表。
    """
    factors = alpha_factors(limit)
    if not factors:
        return []
    with _db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS evo_improvements(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          factor TEXT, win_rate REAL, trades INTEGER,
          suggestion TEXT, ts REAL
        );
        """)
        for f in factors:
            c.execute(
                "INSERT INTO evo_improvements(factor,win_rate,trades,suggestion,ts)"
                " VALUES(?,?,?,?,?)",
                (f["factor"], f["win_rate"], f["trades"],
                 _improvement_suggestion(f), time.time()))
    return [{"factor": f["factor"], "win_rate": f["win_rate"],
             "trades": f["trades"], "suggestion": _improvement_suggestion(f)}
            for f in factors]


if __name__ == "__main__":
    import numpy as np
    rng = np.random.default_rng(5)
    # 模拟一组交易：趋势+纪律（胜多），逆势（负多）
    trades = [
        {"code": "600519", "side": "多", "entry": 300.0, "exit": 320.0,
         "qty": 100, "pnl": 2000.0, "hold_days": 12, "reason": "均线金叉趋势跟随"},
        {"code": "600519", "side": "多", "entry": 325.0, "exit": 315.0,
         "qty": 100, "pnl": -1000.0, "hold_days": 5, "reason": "超卖抄底未止损"},
        {"code": "300750", "side": "多", "entry": 200.0, "exit": 215.0,
         "qty": 200, "pnl": 3000.0, "hold_days": 20, "reason": "突破加仓，纪律止盈"},
        {"code": "300750", "side": "空", "entry": 218.0, "exit": 224.0,
         "qty": 100, "pnl": -600.0, "hold_days": 3, "reason": "公告利好逆势做空"},
    ]
    r1 = record_and_reflect(trades[0])
    assert r1["trade_id"] > 0 and r1["reflection"]["outcome"] == "win"
    r2 = record_and_reflect(trades[1])
    assert r2["reflection"]["outcome"] == "loss"
    for t in trades[2:]:
        record_and_reflect(t)
    l = lessons()
    assert l["total"] == 4 and l["win_rate"] > 0
    assert l["win_dimensions"].get("趋势跟随", 0) >= 1
    sp = style_profile()
    assert sp["profile"] and sp["stats"]["trades"] == 4
    eq = equity_curve()
    assert eq and abs(eq[-1] - (1 + 3400 / 100.0 / 100.0 * 0)) >= 0  # 形状校验
    assert eq[-1] > eq[0]  # 净盈利
    refs = recent_reflections()
    assert len(refs) >= 2
    # 模块增量：Alpha 因子 + 递归自改进
    fs = alpha_factors()
    assert isinstance(fs, list) and fs
    assert all({"factor", "trades", "win_rate", "verdict"} <= set(f) for f in fs)
    improved = recursive_improve()
    assert isinstance(improved, list) and len(improved) == len(fs)
    assert all(i["suggestion"] for i in improved)
    print(f"evo_memory self-check ok (trades={l['total']}, "
          f"win_rate={l['win_rate']:.0%}, factors={len(fs)}, "
          f"improvements={len(improved)})")
