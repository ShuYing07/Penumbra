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


# ---------- 高保真模拟交易（模块六）----------
# 市价 / 限价 / 止损三种订单 + 真实摩擦成本：
#   佣金 0.025%/边（最低 5 元，A股口径；美股/加密按比例）、
#   印花税 0.1%（仅卖出，A股口径）、滑点 0.1%。
COMMISSION_RATE = 0.00025   # 佣金 0.025%
COMMISSION_MIN = 5.0        # A股最低佣金 5 元
STAMP_TAX_RATE = 0.001      # 印花税 0.1%（仅卖出）
SLIPPAGE_RATE = 0.001       # 滑点 0.1%


def _apply_fees(amount: float, side: str, market: str) -> float:
    """按市场口径计算买入/卖出的摩擦成本合计。"""
    if market == "US":
        commission = max(amount * COMMISSION_RATE, 0.0)  # 美股按比例
    elif market == "CRYPTO":
        commission = amount * 0.0004  # 交易所 taker 费率约 0.04%
    else:
        commission = max(amount * COMMISSION_RATE, COMMISSION_MIN)  # A股/港股
    tax = amount * STAMP_TAX_RATE if side == "卖出" and market in ("CN", "HK") else 0.0
    slippage = amount * SLIPPAGE_RATE
    return round(commission + tax + slippage, 2)


def place_order(ticker: str, market: str, side: str = "买入",
                order_type: str = "market", qty: float = 0,
                price: float = 0, limit_price: float = 0,
                stop_price: float = 0) -> dict:
    """手动高保真下单（市价/限价/止损）。

    - market:  CN/HK/US/CRYPTO
    - side:    买入 / 卖出
    - order_type: market（现价成交）/ limit（限价，仅当现价达到限价才成交）
                 / stop（止损触发，仅当现价越过触发价才成交）
    - qty: 股数（CN/HK 自动取整手 100）
    - price: 当前参考价（现价）
    - limit_price / stop_price: 限价 / 止损触发价
    返回成交或未成交说明 dict；未成交时 shares=0、note 说明原因。
    """
    init()
    ticker = (ticker or "").strip().upper()
    if not ticker or price <= 0:
        return {"side": side, "ticker": ticker, "order_type": order_type,
                "shares": 0, "price": price, "amount": 0,
                "note": "参数无效：缺少代码或现价非正"}
    # 订单类型有效性
    if order_type not in ("market", "limit", "stop"):
        return {"side": side, "ticker": ticker, "order_type": order_type,
                "shares": 0, "price": price, "amount": 0,
                "note": f"不支持的订单类型：{order_type}"}
    # 条件单：不满足触发条件 → 未成交（模拟挂单）
    # 限价单：买入须现价≤限价，卖出须现价≥限价
    if order_type == "limit":
        if (side == "买入" and price > limit_price) or (side == "卖出" and price < limit_price):
            return {"side": side, "ticker": ticker, "order_type": order_type,
                    "shares": 0, "price": price, "amount": 0,
                    "note": f"限价未触发（现价 {price}，限价 {limit_price}）"}
    elif order_type == "stop":
        # 止损单：买入为向上突破触发，卖出为向下跌破触发
        if (side == "买入" and price < stop_price) or (side == "卖出" and price > stop_price):
            return {"side": side, "ticker": ticker, "order_type": order_type,
                    "shares": 0, "price": price, "amount": 0,
                    "note": f"止损未触发（现价 {price}，触发价 {stop_price}）"}

    # 成交价 = 现价 + 滑点（买入向上 / 卖出向下）
    fill_price = round(price * (1 + SLIPPAGE_RATE if side == "买入" else 1 - SLIPPAGE_RATE), 4)
    # 整手规则
    if qty <= 0:
        return {"side": side, "ticker": ticker, "order_type": order_type,
                "shares": 0, "price": fill_price, "amount": 0, "note": "数量需大于 0"}
    if market in ("CN", "HK"):
        qty = float(int(qty // 100) * 100)
        if qty <= 0:
            return {"side": side, "ticker": ticker, "order_type": order_type,
                    "shares": 0, "price": fill_price, "amount": 0,
                    "note": "数量不足一手（A股/港股按 100 股整手）"}

    amount = round(qty * fill_price, 2)
    fees = _apply_fees(amount, side, market)
    with get_conn() as conn:
        cash = conn.execute("SELECT cash FROM paper_account WHERE id=1").fetchone()[0]
        pos = conn.execute(
            "SELECT shares, avg_cost FROM paper_positions WHERE ticker=?",
            (ticker,)).fetchone()
        shares_now, avg_cost = (pos if pos else (0.0, 0.0))
        trade: dict | None = None
        if side == "买入":
            if cash < amount + fees:
                return {"side": side, "ticker": ticker, "order_type": order_type,
                        "shares": 0, "price": fill_price, "amount": amount,
                        "note": f"现金不足（需 {amount + fees}，可用 {cash:.2f}）"}
            new_shares = shares_now + qty
            new_cost = (avg_cost * shares_now + amount) / new_shares if new_shares else 0
            conn.execute("UPDATE paper_account SET cash=? WHERE id=1",
                         (round(cash - amount - fees, 2),))
            conn.execute(
                """INSERT INTO paper_positions(ticker,market,shares,avg_cost,last_price,updated_at)
                   VALUES(?,?,?,?,?,?)
                   ON CONFLICT(ticker) DO UPDATE SET shares=?, avg_cost=?, last_price=?,
                   updated_at=?""",
                (ticker, market, new_shares, new_cost, fill_price,
                 now_cn().isoformat(timespec="seconds"),
                 new_shares, new_cost, fill_price, now_cn().isoformat(timespec="seconds")))
            trade = _record(conn, ticker, market, "买入", qty, fill_price, amount, None,
                            f"{order_type}单 含费 {fees}")
        elif side == "卖出":
            if shares_now <= 0:
                return {"side": side, "ticker": ticker, "order_type": order_type,
                        "shares": 0, "price": fill_price, "amount": 0,
                        "note": "无持仓可卖"}
            sell_qty = min(qty, shares_now)
            sell_amount = round(sell_qty * fill_price, 2)
            remain = shares_now - sell_qty
            if remain <= 0:
                conn.execute("DELETE FROM paper_positions WHERE ticker=?", (ticker,))
            else:
                conn.execute("UPDATE paper_positions SET shares=?, last_price=?, updated_at=?",
                             (remain, fill_price, now_cn().isoformat(timespec="seconds")),
                             )
            conn.execute("UPDATE paper_account SET cash=? WHERE id=1",
                         (round(cash + sell_amount - fees, 2),))
            trade = _record(conn, ticker, market, "卖出", sell_qty, fill_price, sell_amount,
                            None, f"{order_type}单 含费 {fees}")
        _snapshot(conn, None)
    return trade or {"side": side, "ticker": ticker, "order_type": order_type,
                     "shares": 0, "price": fill_price, "amount": 0, "note": "未成交"}


def equity_curve(limit: int = 500) -> list[dict]:
    init()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT ts, total FROM paper_equity ORDER BY ts ASC").fetchall()[-limit:]
        return [{"ts": r[0], "total": r[1]} for r in rows]
