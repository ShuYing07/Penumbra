# -*- coding: utf-8 -*-
"""策略回测引擎（单标的、日线、单向做多、t+1 开盘成交，无前视偏差）。

纪律：
1. 信号在第 t 日收盘后用截至 t 的数据生成，成交价 = t+1 开盘价（信号日为最后一根 K 线则不成交）；
2. 指标预热（NaN）窗口内不产生信号；
3. 真实成本：佣金（最低收费）+ 印花税（A股/港股卖出；ETF 免）+ 过户费/杂费 + 滑点（bps）；
4. 单标的、只持多/空仓两态，all-in/all-out（仓位比例可配），不杠杆不做空；
5. CN/HK 整手 100（港股每手 MVP 统一近似），US 4 位小数，CRYPTO 6 位小数。

纯 pandas/numpy 实现，无网络、无 IO、无 LLM，可重复、可单测。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import pandas as pd

from core.quant.indicators import ema, rsi, sma

TRADING_DAYS = 252
MIN_BARS = 30  # 指标最大预热需求（MACD slow=26）+ 余量

# ---------------------------------------------------------------------------
# 费率模型
# ---------------------------------------------------------------------------

@dataclass
class FeeModel:
    commission_rate: float = 0.00025   # 佣金费率（双边）
    min_commission: float = 5.0        # 单笔最低佣金（元）
    stamp_tax_sell: float = 0.0        # 印花税（仅卖出），A股 0.0005
    transfer_fee: float = 0.0          # 过户费（双边），A股 0.00001
    slippage_bps: float = 5.0          # 滑点（基点，1bp=0.01%）

    def buy_fee(self, amount: float) -> float:
        comm = max(amount * self.commission_rate, self.min_commission)
        return comm + amount * self.transfer_fee

    def sell_fee(self, amount: float) -> float:
        comm = max(amount * self.commission_rate, self.min_commission)
        return comm + amount * self.stamp_tax_sell + amount * self.transfer_fee

    def fill_price(self, price: float, side: str) -> float:
        s = self.slippage_bps / 10000.0
        return price * (1 + s) if side == "买入" else price * (1 - s)


def default_fee(market: str, ticker: str | None = None) -> FeeModel:
    """按市场（+标的类型）给默认费率（可被 BacktestConfig 覆盖）。

    - CN 股票：佣金万2.5(min5) + 卖出印花税千0.5 + 双边过户费十万1
    - CN ETF：佣金万2.5(min5)，免印花税、免过户费
    - HK：佣金万3 + 卖出印花税0.13% + 双边杂费约万0.3（徵费/结算费简化，计入过户费字段）
    - CRYPTO：千1，无税；US 及其他：万3，无税
    """
    if market == "CN":
        if ticker and _is_cn_etf(ticker):
            return FeeModel(commission_rate=0.00025, min_commission=5.0,
                            stamp_tax_sell=0.0, transfer_fee=0.0, slippage_bps=5.0)
        return FeeModel(commission_rate=0.00025, min_commission=5.0,
                        stamp_tax_sell=0.0005, transfer_fee=0.00001, slippage_bps=5.0)
    if market == "HK":
        return FeeModel(commission_rate=0.0003, min_commission=0.0,
                        stamp_tax_sell=0.0013, transfer_fee=0.00003, slippage_bps=8.0)
    if market == "CRYPTO":
        return FeeModel(commission_rate=0.001, min_commission=0.0,
                        stamp_tax_sell=0.0, transfer_fee=0.0, slippage_bps=10.0)
    # 美股及其他：佣金万 3，无印花税/过户费
    return FeeModel(commission_rate=0.0003, min_commission=0.0,
                    stamp_tax_sell=0.0, transfer_fee=0.0, slippage_bps=5.0)


def _is_cn_etf(ticker: str) -> bool:
    # 延迟导入避免 quant→data 层级耦合
    from core.data.service import is_cn_etf
    return is_cn_etf(ticker)


# ---------------------------------------------------------------------------
# 配置与结果
# ---------------------------------------------------------------------------

@dataclass
class BacktestConfig:
    ticker: str = ""
    market: str = "CN"
    init_capital: float = 1_000_000.0
    position_pct: float = 100.0       # 每次买入占当时权益比例
    start: str | None = None          # YYYY-MM-DD（含）
    end: str | None = None            # YYYY-MM-DD（含）
    fee: FeeModel | None = None

    def resolve_fee(self) -> FeeModel:
        return self.fee or default_fee(self.market, self.ticker or None)


@dataclass
class BacktestResult:
    ticker: str
    market: str
    strategy: str
    params: dict
    config_snapshot: dict
    equity: pd.DataFrame              # date(index) strategy/benchmark/cash/market_value
    trades: pd.DataFrame              # 成交流水
    metrics: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 策略注册表：signal 1=买 / -1=卖 / 0=无（持仓状态由引擎管，重复信号自动忽略）
# ---------------------------------------------------------------------------

def _sig_rsi(df: pd.DataFrame, p: dict) -> pd.Series:
    n = int(p.get("rsi_period", 14))
    buy_thr = float(p.get("buy_thr", 30))
    sell_thr = float(p.get("sell_thr", 70))
    r = rsi(df["close"], n)
    sig = pd.Series(0, index=df.index, dtype=int)
    sig[r < buy_thr] = 1
    sig[r > sell_thr] = -1
    return sig


def _sig_ma_cross(df: pd.DataFrame, p: dict) -> pd.Series:
    fast_n = int(p.get("fast", 5))
    slow_n = int(p.get("slow", 20))
    fast, slow = sma(df["close"], fast_n), sma(df["close"], slow_n)
    sig = pd.Series(0, index=df.index, dtype=int)
    golden = (fast > slow) & (fast.shift(1) <= slow.shift(1))
    death = (fast < slow) & (fast.shift(1) >= slow.shift(1))
    sig[golden] = 1
    sig[death] = -1
    return sig


def _sig_macd_cross(df: pd.DataFrame, p: dict) -> pd.Series:
    fast = int(p.get("macd_fast", 12))
    slow = int(p.get("macd_slow", 26))
    sig_n = int(p.get("macd_signal", 9))
    dif = ema(df["close"], fast) - ema(df["close"], slow)
    dea = dif.ewm(span=sig_n, adjust=False).mean()
    s = pd.Series(0, index=df.index, dtype=int)
    golden = (dif > dea) & (dif.shift(1) <= dea.shift(1))
    death = (dif < dea) & (dif.shift(1) >= dea.shift(1))
    s[golden] = 1
    s[death] = -1
    return s


STRATEGIES: dict[str, Callable[[pd.DataFrame, dict], pd.Series]] = {
    "rsi_reversion": _sig_rsi,
    "ma_cross": _sig_ma_cross,
    "macd_cross": _sig_macd_cross,
}

# UI/CLI 元信息（参数名、中文标签、默认值）——后续加策略在此登记即可
STRATEGY_META: dict[str, dict] = {
    "rsi_reversion": {
        "label": "RSI 超卖反弹",
        "desc": "RSI 低于阈值买入，高于阈值卖出（均值回归）",
        "params": [("rsi_period", "RSI周期", 14), ("buy_thr", "买入阈值", 30),
                   ("sell_thr", "卖出阈值", 70)],
    },
    "ma_cross": {
        "label": "均线金叉死叉",
        "desc": "短均线上穿长均线买入，下穿卖出（趋势跟随）",
        "params": [("fast", "短均线", 5), ("slow", "长均线", 20)],
    },
    "macd_cross": {
        "label": "MACD 金叉死叉",
        "desc": "DIF 上穿 DEA 买入，下穿卖出（趋势跟随）",
        "params": [("macd_fast", "快线", 12), ("macd_slow", "慢线", 26),
                   ("macd_signal", "信号线", 9)],
    },
    "buy_hold": {
        "label": "买入持有（基准）",
        "desc": "首日开盘满仓买入并持有到期末",
        "params": [],
    },
}

DEFAULT_PARAMS: dict[str, dict] = {
    k: {name: default for name, _label, default in meta["params"]}
    for k, meta in STRATEGY_META.items() if meta["params"]
}


def strategy_choices() -> list[tuple[str, str]]:
    """[(key, 中文标签)]，供 UI 下拉。"""
    return [(k, STRATEGY_META[k]["label"]) for k in ("rsi_reversion", "ma_cross", "macd_cross", "buy_hold")]


# ---------------------------------------------------------------------------
# 交易单位
# ---------------------------------------------------------------------------

# 整手 100 的市场（港股真实每手因股而异 100/200/500…，yfinance 不提供 lot size，
# MVP 统一按 100 近似；A股股票/ETF 均为 100 股/份）
_LOT100_MARKETS = ("CN", "HK")


def _lot_shares(market: str, amount: float, price: float) -> float:
    """按市场把金额换成股数；不足最小交易单位返回 0。"""
    if amount <= 0 or price <= 0:
        return 0.0
    if market in _LOT100_MARKETS:
        lots = int(amount // (price * 100))
        return float(lots * 100)
    digits = 6 if market == "CRYPTO" else 4
    return round(amount / price, digits)


def _size_position(market: str, budget: float, price: float, fee: "FeeModel"):
    """在预算内测算可买股数（含费、含滑点价）；不足 1 手返回 (0,0,0)。"""
    qty = _lot_shares(market, budget, price)
    digits = 6 if market == "CRYPTO" else 4
    lot100 = market in _LOT100_MARKETS
    while qty > 0:
        amount = qty * price
        f = fee.buy_fee(amount)
        if amount + f <= budget + 1e-6:
            return qty, amount, f
        qty = qty - 100 if lot100 else round(qty * 0.99, digits)
    return 0.0, 0.0, 0.0


# ---------------------------------------------------------------------------
# 引擎主体
# ---------------------------------------------------------------------------

def run_backtest(df: pd.DataFrame, market: str, strategy: str,
                 params: dict | None = None,
                 config: BacktestConfig | None = None) -> BacktestResult:
    """跑一次回测。纯计算，不联网不写库。"""
    cfg = config or BacktestConfig(market=market)
    fee = cfg.resolve_fee()
    params = {**DEFAULT_PARAMS.get(strategy, {}), **(params or {})}

    if df is None or len(df) < MIN_BARS:
        raise ValueError(f"行情数据不足：需≥{MIN_BARS} 根日线，实际 {0 if df is None else len(df)} 根")
    if strategy not in STRATEGY_META:
        raise ValueError(f"未知策略：{strategy}（可选 {list(STRATEGY_META)}）")

    data = df.sort_index()
    if cfg.start:
        data = data[data.index >= pd.Timestamp(cfg.start)]
    if cfg.end:
        data = data[data.index <= pd.Timestamp(cfg.end)]
    if len(data) < MIN_BARS:
        raise ValueError(f"筛选起止日期后数据不足：{len(data)} 根（需≥{MIN_BARS}）")

    # 信号（buy_hold 在引擎内特判）
    signals = STRATEGIES[strategy](data, params) if strategy in STRATEGIES else None

    cash = float(cfg.init_capital)
    shares = 0.0
    entry_date = None
    entry_cost_total = 0.0  # 买入总花费（含费），用于逐轮盈亏
    pending: int | None = None  # 上一交易日收盘产生、待今日开盘成交的信号
    pending_reason = ""

    trades_rows: list[dict] = []
    rounds: list[dict] = []  # 已平仓回合（买-卖），用于胜率/盈亏比
    eq_rows: list[dict] = []

    opens = data["open"].to_numpy()
    closes = data["close"].to_numpy()
    dates = data.index

    def _equity(i: int) -> float:
        return cash + shares * float(closes[i])

    def _do_fill(i: int, sig: int) -> None:
        nonlocal cash, shares, entry_date, entry_cost_total
        raw_price = float(opens[i])
        if not np.isfinite(raw_price) or raw_price <= 0:
            return
        side = "买入" if sig == 1 else "卖出"
        price = fee.fill_price(raw_price, side)

        if sig == 1 and shares == 0:
            budget = _equity(i - 1) * cfg.position_pct / 100.0 if i > 0 else cash * cfg.position_pct / 100.0
            budget = min(budget, cash)
            qty, amount, f = _size_position(market, budget, price, fee)
            if qty <= 0:
                return
            cash -= amount + f
            shares = qty
            entry_date = dates[i]
            entry_cost_total = amount + f
            trades_rows.append({"signal_date": dates[i - 1].strftime("%Y-%m-%d") if i > 0 else dates[i].strftime("%Y-%m-%d"),
                                "fill_date": dates[i].strftime("%Y-%m-%d"),
                                "side": "买入", "price": round(price, 4), "shares": qty,
                                "amount": round(amount, 2), "fee": round(f, 2),
                                "reason": pending_reason})
        elif sig == -1 and shares > 0:
            amount = shares * price
            f = fee.sell_fee(amount)
            cash += amount - f
            hold_days = int((dates[i] - entry_date).days) if entry_date is not None else 0
            pnl = (amount - f) - entry_cost_total
            rounds.append({"pnl": pnl, "hold_days": hold_days})
            trades_rows.append({"signal_date": dates[i - 1].strftime("%Y-%m-%d"),
                                "fill_date": dates[i].strftime("%Y-%m-%d"),
                                "side": "卖出", "price": round(price, 4), "shares": shares,
                                "amount": round(amount, 2), "fee": round(f, 2),
                                "reason": pending_reason, "pnl": round(pnl, 2),
                                "hold_days": hold_days})
            shares = 0.0
            entry_date = None
            entry_cost_total = 0.0

    first_open = float(opens[0])
    for i in range(len(data)):
        # 1) 今日开盘成交昨日信号
        if pending is not None:
            _do_fill(i, pending)
            pending = None
            pending_reason = ""

        # buy_hold：首日开盘直接满仓（基准策略，允许碎股，无信号日）
        if strategy == "buy_hold" and i == 0 and shares == 0:
            price = fee.fill_price(first_open, "买入")
            budget = cash * cfg.position_pct / 100.0
            qty, amount, f = _size_position(market, budget, price, fee)
            if qty > 0:
                cash -= amount + f
                shares = qty
                entry_date = dates[i]
                entry_cost_total = amount + f
                trades_rows.append({"signal_date": dates[i].strftime("%Y-%m-%d"),
                                    "fill_date": dates[i].strftime("%Y-%m-%d"),
                                    "side": "买入", "price": round(price, 4), "shares": qty,
                                    "amount": round(amount, 2), "fee": round(f, 2),
                                    "reason": "首日开盘买入"})

        # 2) 今日收盘盯市记权益
        total = _equity(i)
        bench = cfg.init_capital * float(closes[i]) / first_open if first_open > 0 else cfg.init_capital
        eq_rows.append({"date": dates[i].strftime("%Y-%m-%d"),
                        "strategy": round(total, 2),
                        "benchmark": round(bench, 2),
                        "cash": round(cash, 2),
                        "market_value": round(shares * float(closes[i]), 2)})

        # 3) 今日收盘生信号 → 明日开盘成交（最后一根不挂单）
        if signals is not None and i < len(data) - 1:
            s = int(signals.iloc[i])
            if s == 1 and shares == 0:
                pending, pending_reason = 1, f"{STRATEGY_META[strategy]['label']}买入信号"
            elif s == -1 and shares > 0:
                pending, pending_reason = -1, f"{STRATEGY_META[strategy]['label']}卖出信号"

    equity = pd.DataFrame(eq_rows).set_index("date")
    trades = pd.DataFrame(trades_rows)
    metrics = compute_metrics(equity, trades, rounds, cfg)

    snap = {"init_capital": cfg.init_capital, "position_pct": cfg.position_pct,
            "start": cfg.start, "end": cfg.end,
            "fee": {"commission_rate": fee.commission_rate, "min_commission": fee.min_commission,
                    "stamp_tax_sell": fee.stamp_tax_sell, "transfer_fee": fee.transfer_fee,
                    "slippage_bps": fee.slippage_bps}}
    return BacktestResult(ticker=cfg.ticker, market=market, strategy=strategy,
                          params=params, config_snapshot=snap,
                          equity=equity, trades=trades, metrics=metrics)


# ---------------------------------------------------------------------------
# 绩效指标
# ---------------------------------------------------------------------------

def compute_metrics(equity: pd.DataFrame, trades: pd.DataFrame,
                    rounds: list[dict], cfg: BacktestConfig) -> dict:
    init = float(cfg.init_capital)
    strat = equity["strategy"].astype(float)
    bench = equity["benchmark"].astype(float)
    final = float(strat.iloc[-1])

    total_ret = final / init - 1.0
    bench_ret = float(bench.iloc[-1]) / init - 1.0

    days = len(strat)
    years = days / TRADING_DAYS
    annual = (final / init) ** (1.0 / years) - 1.0 if years > 0 and final > 0 else 0.0
    bench_annual = (float(bench.iloc[-1]) / init) ** (1.0 / years) - 1.0 if years > 0 and float(bench.iloc[-1]) > 0 else 0.0

    # 最大回撤
    cummax = strat.cummax()
    dd = strat / cummax - 1.0
    max_dd = float(dd.min())

    # 夏普（rf=0，日收益年化）
    rets = strat.pct_change().dropna()
    sharpe = float(rets.mean() / rets.std() * np.sqrt(TRADING_DAYS)) if len(rets) > 1 and rets.std() > 0 else 0.0

    # 胜率 / 盈亏比 / 平均持仓（按完整买-卖回合）
    n_round = len(rounds)
    wins = [r["pnl"] for r in rounds if r["pnl"] > 0]
    losses = [r["pnl"] for r in rounds if r["pnl"] <= 0]
    win_rate = len(wins) / n_round if n_round else 0.0
    avg_win = float(np.mean(wins)) if wins else 0.0
    avg_loss = float(np.mean(losses)) if losses else 0.0
    pl_ratio = avg_win / abs(avg_loss) if avg_loss != 0 else (float("inf") if avg_win > 0 else 0.0)
    avg_hold = float(np.mean([r["hold_days"] for r in rounds])) if n_round else 0.0

    total_fee = float(trades["fee"].sum()) if len(trades) else 0.0

    return {
        "final_equity": round(final, 2),
        "total_return_pct": round(total_ret * 100, 2),
        "annual_return_pct": round(annual * 100, 2),
        "benchmark_return_pct": round(bench_ret * 100, 2),
        "benchmark_annual_pct": round(bench_annual * 100, 2),
        "excess_return_pct": round((total_ret - bench_ret) * 100, 2),
        "max_drawdown_pct": round(max_dd * 100, 2),
        "sharpe": round(sharpe, 3),
        "win_rate_pct": round(win_rate * 100, 2),
        "profit_loss_ratio": round(pl_ratio, 2) if np.isfinite(pl_ratio) else None,
        "trade_count": int(len(trades)),
        "closed_rounds": n_round,
        "avg_hold_days": round(avg_hold, 1),
        "total_fee": round(total_fee, 2),
        "bars": days,
    }


METRIC_LABELS = [
    ("final_equity", "期末权益(元)"),
    ("total_return_pct", "总收益率(%)"),
    ("annual_return_pct", "年化收益(%)"),
    ("benchmark_return_pct", "基准收益(%)"),
    ("excess_return_pct", "超额收益(%)"),
    ("max_drawdown_pct", "最大回撤(%)"),
    ("sharpe", "夏普比率"),
    ("win_rate_pct", "胜率(%)"),
    ("profit_loss_ratio", "盈亏比"),
    ("trade_count", "成交笔数"),
    ("closed_rounds", "完整回合"),
    ("avg_hold_days", "平均持仓(天)"),
    ("total_fee", "总费用(元)"),
]
