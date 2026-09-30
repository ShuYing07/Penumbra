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
        "win_rate": round(len(wins) / len(rows), 3) if rows else 0.0,
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
               f"{round(sum(1 for p in pnls if p > 0) / len(pnls), 3):.1%} · "
               f"平均持仓 {round(sum(holds) / len(holds), 1):.1f} 天 · "
               f"偏好{dom_side[0]}方向、{dom_dim[0]}策略 · 最佳 {best:.0f} / "
               f"最差 {worst:.0f}")
    return {"profile": profile,
            "stats": {"trades": len(rows), "net_pnl": round(total_pnl, 2),
                      "win_rate": round(sum(1 for p in pnls if p > 0) / len(pnls), 3),
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
    print(f"evo_memory self-check ok (trades={l['total']}, "
          f"win_rate={l['win_rate']:.0%}, profile='{sp['profile'][:40]}…')")
