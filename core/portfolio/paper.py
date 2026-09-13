# -*- coding: utf-8 -*-
"""模拟盘：虚拟账户按分析决策成交（只做模拟，绝不接实盘）。

- 初始虚拟资金默认 100 万（STOCKAI_PAPER_CAPITAL 可改）；
- 买入：按 final.position_pct 占总资产比例买入；A股按 100 股整手，美股/加密允许碎股；
- 卖出/回避：清掉该标的全部持仓；
- 观望：不动；
- 每次行情刷新记一条净值快照（paper_equity），供收益曲线展示。
"""
from __future__ import annotations

import logging
import os

from core.config import now_cn
from core.data.cache import get_conn

log = logging.getLogger("stockai.paper")

INIT_CAPITAL = float(os.environ.get("STOCKAI_PAPER_CAPITAL", "1000000"))

_SCHEMA = """
CREATE TABLE IF NOT EXISTS paper_account(
  id INTEGER PRIMARY KEY CHECK(id=1),
  cash REAL, init_capital REAL, created_at TEXT);
CREATE TABLE IF NOT EXISTS paper_positions(
  ticker TEXT PRIMARY KEY, market TEXT, shares REAL,
  avg_cost REAL, last_price REAL, updated_at TEXT);
CREATE TABLE IF NOT EXISTS paper_trades(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, ticker TEXT, market TEXT,
  side TEXT, shares REAL, price REAL, amount REAL, decision_id INTEGER, note TEXT);
CREATE TABLE IF NOT EXISTS paper_equity(
  ts TEXT PRIMARY KEY, cash REAL, market_value REAL, total REAL);
"""

_BUY_ACTIONS = ("买入", "强烈买入")
_SELL_ACTIONS = ("卖出", "回避")


def init() -> None:
    with get_conn() as conn:
        conn.executescript(_SCHEMA)
        row = conn.execute("SELECT cash FROM paper_account WHERE id=1").fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO paper_account(id,cash,init_capital,created_at) VALUES(1,?,?,?)",
                (INIT_CAPITAL, INIT_CAPITAL, now_cn().isoformat(timespec="seconds")))


def reset() -> None:
    """清空模拟盘（慎用）：恢复初始资金，清持仓/成交/净值。"""
    init()
    with get_conn() as conn:
        conn.execute("UPDATE paper_account SET cash=? WHERE id=1", (INIT_CAPITAL,))
        conn.execute("DELETE FROM paper_positions")
        conn.execute("DELETE FROM paper_trades")
        conn.execute("DELETE FROM paper_equity")


def _lot_shares(market: str, amount: float, price: float) -> float:
    """按市场规则把金额换成股数；不足最小单位返回 0。

    CN=A股/ETF 整手100；HK=港股统一按100近似（真实每手因股而异）；
    US 允许 4 位小数碎股；CRYPTO 6 位小数。
    """
    if market in ("CN", "HK"):
        lots = int(amount // (price * 100))
        return float(lots * 100)
    digits = 6 if market == "CRYPTO" else 4
    return round(amount / price, digits)


def execute(state: dict) -> dict | None:
    """把一条分析决策落到模拟盘。返回成交记录 dict；未成交返回 None。"""
    init()
    final = state.get("final") or {}
    action = final.get("action", "")
    ticker = state.get("ticker", "")
    market = state.get("market", "")
    try:
        price = float(final.get("price") or 0)
    except (TypeError, ValueError):
        price = 0.0
    if not ticker or price <= 0:
        return None
    decision_id = state.get("_decision_id")

    with get_conn() as conn:
        cash = conn.execute("SELECT cash FROM paper_account WHERE id=1").fetchone()[0]
        pos = conn.execute(
            "SELECT shares, avg_cost FROM paper_positions WHERE ticker=?", (ticker,)).fetchone()
        shares_now, avg_cost = (pos if pos else (0.0, 0.0))

        trade: dict | None = None
        if action in _BUY_ACTIONS and float(final.get("position_pct") or 0) > 0:
            market_value = _market_value(conn)
            budget = min((cash + market_value) * float(final["position_pct"]) / 100.0, cash)
            shares = _lot_shares(market, budget, price)
            if shares > 0:
                amount = round(shares * price, 2)
                new_shares = shares_now + shares
                new_cost = (avg_cost * shares_now + amount) / new_shares
                conn.execute("UPDATE paper_account SET cash=? WHERE id=1", (cash - amount,))
                conn.execute(
                    """INSERT INTO paper_positions(ticker,market,shares,avg_cost,last_price,updated_at)
                       VALUES(?,?,?,?,?,?)
                       ON CONFLICT(ticker) DO UPDATE SET shares=?, avg_cost=?, last_price=?, updated_at=?""",
                    (ticker, market, new_shares, new_cost, price,
                     now_cn().isoformat(timespec="seconds"),
                     new_shares, new_cost, price, now_cn().isoformat(timespec="seconds")))
                trade = _record(conn, ticker, market, "买入", shares, price, amount, decision_id,
                                f"仓位{final.get('position_pct')}% 置信{final.get('confidence')}%")
        elif action in _SELL_ACTIONS and shares_now > 0:
            amount = round(shares_now * price, 2)
            conn.execute("UPDATE paper_account SET cash=? WHERE id=1", (cash + amount,))
            conn.execute("DELETE FROM paper_positions WHERE ticker=?", (ticker,))
            trade = _record(conn, ticker, market, "卖出", shares_now, price, amount, decision_id,
                            f"成本{avg_cost:.2f} 盈亏{(price / avg_cost - 1) * 100:+.2f}%")

        _snapshot(conn, cash_after=None)
        return trade


def _record(conn, ticker, market, side, shares, price, amount, decision_id, note) -> dict:
    conn.execute(
        """INSERT INTO paper_trades(ts,ticker,market,side,shares,price,amount,decision_id,note)
           VALUES(?,?,?,?,?,?,?,?,?)""",
        (now_cn().isoformat(timespec="seconds"), ticker, market, side, shares, price, amount,
         decision_id, note))
    log.info("模拟盘成交：%s %s %s股 @ %s（%s）", side, ticker, shares, price, note)
    return {"side": side, "ticker": ticker, "shares": shares, "price": price,
            "amount": amount, "note": note}


def _market_value(conn) -> float:
    row = conn.execute("SELECT COALESCE(SUM(shares*last_price),0) FROM paper_positions").fetchone()
    return float(row[0])


def _snapshot(conn, cash_after: float | None) -> None:
    cash = cash_after
    if cash is None:
        cash = conn.execute("SELECT cash FROM paper_account WHERE id=1").fetchone()[0]
    mv = _market_value(conn)
    conn.execute(
        "INSERT OR REPLACE INTO paper_equity(ts,cash,market_value,total) VALUES(?,?,?,?)",
        # 微秒精度：同一秒内多笔成交各留一条快照
        (now_cn().isoformat(), cash, mv, cash + mv))


def mark_to_market(prices: dict[str, float]) -> dict:
    """用最新价更新持仓估值并记录净值快照；返回账户汇总。"""
    init()
    with get_conn() as conn:
        for ticker, price in (prices or {}).items():
            try:
                p = float(price)
            except (TypeError, ValueError):
                continue
            if p > 0:
                conn.execute("UPDATE paper_positions SET last_price=?, updated_at=? WHERE ticker=?",
                             (p, now_cn().isoformat(timespec="seconds"), ticker))
        _snapshot(conn, None)
        return summary()


def summary() -> dict:
    init()
    with get_conn() as conn:
        cash, init_cap = conn.execute(
            "SELECT cash, init_capital FROM paper_account WHERE id=1").fetchone()
        mv = _market_value(conn)
        total = cash + mv
        return {"cash": round(cash, 2), "market_value": round(mv, 2),
                "total": round(total, 2), "init_capital": init_cap,
                "pnl": round(total - init_cap, 2),
                "pnl_pct": round((total / init_cap - 1) * 100, 2) if init_cap else 0.0}


def positions() -> list[dict]:
    init()
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT ticker, market, shares, avg_cost, last_price FROM paper_positions
               ORDER BY shares*last_price DESC""").fetchall()
        return [{"ticker": t, "market": m, "shares": s, "avg_cost": a, "last_price": p,
                 "market_value": round(s * p, 2),
                 "pnl_pct": round((p / a - 1) * 100, 2) if a else 0.0}
                for t, m, s, a, p in rows]


def trades(limit: int = 50) -> list[dict]:
    init()
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT ts, ticker, side, shares, price, amount, decision_id, note
               FROM paper_trades ORDER BY id DESC LIMIT ?""", (limit,)).fetchall()
        keys = ["ts", "ticker", "side", "shares", "price", "amount", "decision_id", "note"]
        return [dict(zip(keys, r)) for r in rows]


def equity_curve(limit: int = 500) -> list[dict]:
    init()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT ts, total FROM paper_equity ORDER BY ts ASC").fetchall()[-limit:]
        return [{"ts": r[0], "total": r[1]} for r in rows]
