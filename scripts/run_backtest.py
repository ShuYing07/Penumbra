# -*- coding: utf-8 -*-
"""策略回测 CLI：在历史日线上回放规则策略，输出全套绩效指标。

示例：
  venv\\Scripts\\python.exe scripts\\run_backtest.py SH600519
  venv\\Scripts\\python.exe scripts\\run_backtest.py SH600519 --strategy ma_cross --fast 5 --slow 20
  venv\\Scripts\\python.exe scripts\\run_backtest.py AAPL --strategy rsi_reversion --buy 30 --sell 70 --start 2022-01-01
  venv\\Scripts\\python.exe scripts\\run_backtest.py SH600519 --strategy buy_hold

纪律：信号 t 日收盘生成 → t+1 开盘成交（无前视）；含佣金/印花税/滑点。
不调用任何大模型，秒级完成，结果落 data/backtests/ 留痕。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.config import DATA_DIR, DISCLAIMER  # noqa: E402
from core.data.service import get_daily, market_of  # noqa: E402
from core.quant.backtest import (  # noqa: E402
    METRIC_LABELS, STRATEGY_META, BacktestConfig, run_backtest,
)

BACKTEST_DIR = DATA_DIR / "backtests"


def _params_for(strategy: str, args: argparse.Namespace) -> dict:
    p: dict = {}
    if strategy == "rsi_reversion":
        p = {"rsi_period": args.rsi_period, "buy_thr": args.buy, "sell_thr": args.sell}
    elif strategy == "ma_cross":
        p = {"fast": args.fast, "slow": args.slow}
    elif strategy == "macd_cross":
        p = {"macd_fast": args.macd_fast, "macd_slow": args.macd_slow,
             "macd_signal": args.macd_signal}
    return p


def main() -> int:
    ap = argparse.ArgumentParser(description="StockAIPredictor 策略回测")
    ap.add_argument("ticker", help="标的，如 SH600519 / AAPL / BTC-USD")
    ap.add_argument("--strategy", default="rsi_reversion",
                    choices=list(STRATEGY_META.keys()),
                    help="策略（默认 rsi_reversion）")
    ap.add_argument("--capital", type=float, default=1_000_000, help="初始资金（默认100万）")
    ap.add_argument("--position", type=float, default=100.0, help="单次买入仓位比例%%（默认100）")
    ap.add_argument("--start", default=None, help="起始日期 YYYY-MM-DD（含）")
    ap.add_argument("--end", default=None, help="结束日期 YYYY-MM-DD（含）")
    # 策略参数
    ap.add_argument("--rsi-period", type=int, default=14)
    ap.add_argument("--buy", type=float, default=30.0, help="RSI 买入阈值（默认30）")
    ap.add_argument("--sell", type=float, default=70.0, help="RSI 卖出阈值（默认70）")
    ap.add_argument("--fast", type=int, default=5, help="短均线周期（默认5）")
    ap.add_argument("--slow", type=int, default=20, help="长均线周期（默认20）")
    ap.add_argument("--macd-fast", type=int, default=12)
    ap.add_argument("--macd-slow", type=int, default=26)
    ap.add_argument("--macd-signal", type=int, default=9)
    ap.add_argument("--no-save", action="store_true", help="只打印不落盘")
    args = ap.parse_args()

    ticker = args.ticker.upper()
    market = market_of(ticker)
    print(f"标的 {ticker}（市场 {market}）取历史日线…")
    df, status = get_daily(ticker)
    print(f"数据状态：{status}，共 {len(df)} 根日线（{df.index[0].date()} ~ {df.index[-1].date()}）")

    cfg = BacktestConfig(ticker=ticker, market=market, init_capital=args.capital,
                         position_pct=args.position, start=args.start, end=args.end)
    params = _params_for(args.strategy, args)

    result = run_backtest(df, market, args.strategy, params, cfg)
    m = result.metrics

    print("\n" + "=" * 56)
    print(f"策略：{STRATEGY_META[args.strategy]['label']}  参数：{result.params}")
    print("=" * 56)
    for key, label in METRIC_LABELS:
        print(f"  {label:<16}: {m.get(key)}")
    print("=" * 56)
    print(f"成交流水（共 {len(result.trades)} 笔）：")
    if len(result.trades):
        print(result.trades.to_string(index=False))
    else:
        print("  （区间内无交易信号）")
    print("\n" + DISCLAIMER)

    if not args.no_save:
        BACKTEST_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = BACKTEST_DIR / f"{ticker}_{args.strategy}_{ts}.json"
        payload = {
            "ticker": ticker, "market": market, "strategy": args.strategy,
            "params": result.params, "config": result.config_snapshot,
            "metrics": m, "generated_at": ts,
            "trades": result.trades.to_dict("records"),
            "equity": result.equity.reset_index().to_dict("records"),
        }
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n结果已保存：{out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
