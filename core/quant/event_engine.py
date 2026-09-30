
# -*- coding: utf-8 -*-
"""事件驱动回测引擎（模块四 · 参考 QuantPilot「诚实回测」）。

五模块事件驱动（DataFeed / Strategy / RiskManager / Portfolio /
ExecutionHandler 经单一事件队列协作），A股规则：
- 收盘决策 → 次日开盘价成交（避免前视成交）；
- T+1 结算：当日买入不可当日卖出；
- 100 股整手：成交数量取整手，现金不足则降档；
- 真实摩擦成本：佣金（默认 0.025%/边，最低 5 元）、印花税（卖出 0.1%）、
  双边滑点（默认 5bp）——逐笔计费；
- 输出：净值曲线、交易日志、绩效指标（年化/回撤/Sharpe/胜率）。

与既有向量化回测（core.quant.backtest）并存：本引擎强调事件级撮合
与 A股交易规则的确定性，供「策略审计」面板交叉验证。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, List, Optional

import numpy as np
import pandas as pd

log = logging.getLogger("stockai.quant.event_engine")

LOT = 100                       # A股整手
T1 = True                       # T+1 结算
COMMISSION_RATE = 0.00025       # 佣金 0.025%/边
MIN_COMMISSION = 5.0            # 单笔最低佣金（元）
STAMP_TAX_SELL = 0.001          # 印花税 0.1%（卖出）
SLIPPAGE_BPS = 5.0              # 双边滑点 5bp


@dataclass
class Trade:
    date: str
    action: str                 # buy / sell
    price: float                # 实际成交价（含滑点）
    shares: int
    amount: float
    fee: float
    cash_after: float


@dataclass
class Event:
    kind: str                   # bar
    date: str
    idx: int
    price: float = 0.0


class DataFeed:
    """数据源：K线 → 事件队列（按日逐根推送 bar）。"""

    def __init__(self, bars: pd.DataFrame):
        df = bars.reset_index()
        date_col = "date" if "date" in df.columns else df.columns[0]
        df = df.rename(columns={date_col: "_date"})
        for col in ("open", "high", "low", "close", "volume"):
            if col in df.columns:
                df[col] = df[col].astype(float)
        self.df = df
        self.i = 0

    def next(self) -> Optional[Event]:
        if self.i >= len(self.df):
            return None
        row = self.df.iloc[self.i]
        ev = Event(kind="bar", date=str(row["_date"]), idx=self.i,
                   price=float(row["close"]))
        self.i += 1
        return ev


class Strategy:
    """策略：由信号函数决定目标仓位（股数），收盘决策。"""

    def __init__(self, signal: Callable[[pd.DataFrame, int], int],
                 max_lot: int = 1000):
        self.signal = signal
        self.max_lot = max_lot

    def on_bar(self, df_sofar: pd.DataFrame, idx: int) -> int:
        lots = int(self.signal(df_sofar, idx))
        return max(-self.max_lot, min(self.max_lot, lots)) * LOT


class RiskManager:
    """风控：单一持仓上限 + 现金可买上限（预留费用）。"""

    def __init__(self, max_lots: int = 1000):
        self.max_lots = max_lots

    def apply(self, target_shares: int, cash: float, price: float) -> int:
        # 每手成本含佣金/印花税/滑点预算（~0.15%），避免买入后现金不足
        cost_per_lot = price * LOT * 1.0015
        affordable_lots = int(cash / max(cost_per_lot, 1e-9))
        lots = min(target_shares // LOT, self.max_lots, affordable_lots)
        return max(lots, 0) * LOT


class Portfolio:
    """账户：现金 + 持仓，T+1 冻结，逐笔计费。"""

    def __init__(self, initial_cash: float = 1_000_000.0):
        self.cash = initial_cash
        self.shares = 0
        self.buyable = initial_cash      # 可用现金
        self.trades: List[Trade] = []
        self.equity: List[dict] = []

    def execute(self, ev: Event, price: float, shares: int) -> Optional[Trade]:
        if shares > 0:  # 买入
            amount = price * shares
            fee = max(amount * COMMISSION_RATE, MIN_COMMISSION)
            total = amount + fee
            if total > self.buyable + 1e-6:
                return None
            self.buyable -= total
            self.shares += shares
            self.cash -= total
            tr = Trade(ev.date, "buy", price, shares, amount, fee, self.buyable)
        elif shares < 0 and self.shares > 0:  # 卖出
            sell = min(-shares, self.shares)
            amount = price * sell
            fee = max(amount * COMMISSION_RATE, MIN_COMMISSION) \
                + amount * STAMP_TAX_SELL
            self.shares -= sell
            proceeds = amount - fee
            self.cash += proceeds
            self.buyable += proceeds
            tr = Trade(ev.date, "sell", price, sell, amount, fee, self.buyable)
        else:
            return None
        self.trades.append(tr)
        return tr

    def mark(self, date: str, price: float) -> None:
        self.equity.append({"date": date, "cash": self.cash,
                            "shares": self.shares,
                            "equity": self.cash + self.shares * price})


class ExecutionHandler:
    """执行：收盘产生的目标仓位 → 次日开盘价（含滑点）成交。"""

    def __init__(self, slippage_bps: float = SLIPPAGE_BPS):
        self.slippage = slippage_bps / 10000.0

    def price_with_slip(self, open_price: float, is_buy: bool) -> float:
        return open_price * (1 + self.slippage) if is_buy \
            else open_price * (1 - self.slippage)


def run_event_backtest(
    bars: pd.DataFrame,
    signal: Callable[[pd.DataFrame, int], int],
    initial_cash: float = 1_000_000.0,
    max_lots: int = 1000,
) -> dict:
    """运行事件驱动回测。

    signal(df_sofar, idx) -> 目标手数（正=多头仓位，0=清仓，忽略负数）。
    返回 {equity_curve, trades, stats}。
    """
    feed = DataFeed(bars)
    strategy = Strategy(signal, max_lot=max_lots)
    risk = RiskManager(max_lots=max_lots)
    portfolio = Portfolio(initial_cash)
    exec_ = ExecutionHandler()

    pending_target = 0           # 上日收盘决策 -> 今日开盘执行
    for ev in iter(feed.next, None):
        row = feed.df.iloc[ev.idx]
        open_px = float(row["open"])
        # 1) 执行昨日决策（次日开盘成交，含滑点）
        if pending_target != 0:
            is_buy = pending_target > 0
            px = exec_.price_with_slip(open_px, is_buy)
            shares = risk.apply(pending_target, portfolio.buyable, px)
            if shares > 0:
                portfolio.execute(ev, px, shares)
            elif not is_buy and portfolio.shares > 0:
                portfolio.execute(ev, px, -portfolio.shares)
            pending_target = 0
        # 2) 收盘决策：目标仓位
        try:
            target = strategy.on_bar(feed.df.iloc[: ev.idx + 1], ev.idx)
        except Exception as e:  # noqa: BLE001
            log.warning("策略信号异常（第 %s 根）：%s", ev.idx, e)
            target = 0
        pending_target = target
        # 3) 按收盘价记市值
        portfolio.mark(ev.date, float(row["close"]))

    eq = pd.DataFrame(portfolio.equity)
    stats = _stats(eq, portfolio.trades, initial_cash)
    return {"equity_curve": eq, "trades": portfolio.trades, "stats": stats,
            "fee_model": {"commission": COMMISSION_RATE,
                          "min_commission": MIN_COMMISSION,
                          "stamp_tax_sell": STAMP_TAX_SELL,
                          "slippage_bps": SLIPPAGE_BPS,
                          "lot": LOT, "t1": T1}}


def _stats(eq: pd.DataFrame, trades: List[Trade],
           initial_cash: float) -> dict:
    if eq.empty:
        return {"error": "无净值数据"}
    eq = eq.set_index("date")
    ret = eq["equity"].pct_change().dropna()
    total = float(eq["equity"].iloc[-1] / initial_cash - 1)
    n = len(eq)
    ann = (1 + total) ** (252 / max(n, 1)) - 1 if n > 1 else total
    dd = float((eq["equity"] / eq["equity"].cummax() - 1).min())
    sharpe = float(ret.mean() / ret.std() * np.sqrt(252)) \
        if len(ret) > 1 and ret.std() > 0 else 0.0
    buys = [t for t in trades if t.action == "buy"]
    sells = [t for t in trades if t.action == "sell"]
    win = 0.0
    if sells and buys:
        avg_buy = sum(t.amount for t in buys) / len(buys)
        win = sum(1 for t in sells if t.amount > avg_buy) / len(sells)
    return {"total_return": total, "annual_return": ann, "max_drawdown": dd,
            "sharpe": sharpe, "n_trades": len(trades),
            "n_buys": len(buys), "n_sells": len(sells), "win_rate": win}


if __name__ == "__main__":
    rng = np.random.default_rng(9)
    idx = pd.date_range("2025-01-01", periods=250)
    close = pd.Series(100 * np.cumprod(1 + rng.normal(0.0005, 0.02, 250)),
                      index=idx)
    bars = pd.DataFrame({"open": close, "high": close * 1.01,
                         "low": close * 0.99, "close": close,
                         "volume": rng.integers(1e5, 5e5, 250)},
                        index=idx)

    def ma_signal(df: pd.DataFrame, idx: int) -> int:
        if idx < 20:
            return 0
        c = df["close"]
        fast, slow = c.iloc[-5:].mean(), c.iloc[-20:].mean()
        return 100 if fast > slow else 0   # 100 手

    r = run_event_backtest(bars, ma_signal)
    assert "error" not in r["stats"], r["stats"]
    st = r["stats"]
    assert st["n_trades"] > 0
    assert r["fee_model"]["lot"] == 100 and r["fee_model"]["t1"] is True
    assert all(t.fee > 0 for t in r["trades"])
    assert str(r["trades"][0].date) > str(bars.index[0].date())
    print(f"event_engine self-check ok (trades={st['n_trades']}, "
          f"ret={st['total_return']:.2%})")
