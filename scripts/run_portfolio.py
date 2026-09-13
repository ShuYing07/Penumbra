# -*- coding: utf-8 -*-
"""多标的组合回测 CLI：统一策略 + 目标权重 + 漂移/定期再平衡，对比 buy_hold 基准。

用法：
  run_portfolio.py SH600519 SH510300 0700.HK
  run_portfolio.py SH600519 SH510300 --weights 0.6,0.4 --rebalance quarter
  run_portfolio.py SH510300 0700.HK --strategy ma_cross --params '{\"fast\":5,\"slow\":20}'

说明：各标的先独立跑策略（含真实费率），组合在公共交易日按日收益加权；
基准=同权重同再平衡规则的 buy_hold 组合；v1 不计再平衡换手费。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.config import DATA_DIR, DISCLAIMER, now_cn, setup_logging
from core.portfolio.multi_backtest import REBALANCE_CHOICES, HoldingSpec, run_portfolio
from core.quant.backtest import STRATEGY_META


def main() -> int:
    ap = argparse.ArgumentParser(description="StockAIPredictor 多标的组合回测")
    ap.add_argument("tickers", nargs="+", help="≥2 个标的，如 SH600519 SH510300 0700.HK")
    ap.add_argument("--weights", default=None,
                    help="逗号分隔权重（默认等权），如 0.6,0.3,0.1；自动归一化")
    ap.add_argument("--strategy", default="buy_hold",
                    choices=list(STRATEGY_META.keys()), help="全组合统一策略")
    ap.add_argument("--params", default=None, help='策略参数 JSON，如 \'{"fast":5,"slow":20}\'')
    ap.add_argument("--rebalance", default="none", choices=REBALANCE_CHOICES,
                    help="再平衡周期 none/month/quarter/year（默认 none 漂移）")
    ap.add_argument("--start", default=None)
    ap.add_argument("--end", default=None)
    args = ap.parse_args()

    setup_logging()
    tickers = [t.upper() for t in args.tickers]
    if len(tickers) < 2:
        print("组合回测至少需要 2 个标的（单标的请用 run_backtest.py）")
        return 2
    weights = None
    if args.weights:
        try:
            weights = [float(x) for x in args.weights.split(",")]
        except ValueError:
            print("权重解析失败，应为逗号分隔数字，如 0.6,0.4")
            return 2
    params = None
    if args.params:
        try:
            params = json.loads(args.params)
        except json.JSONDecodeError as e:
            print(f"参数 JSON 解析失败：{e}")
            return 2

    specs = [HoldingSpec(t, w) for t, w in zip(tickers, weights or [1.0] * len(tickers))]
    print(f"组合回测：{tickers}｜策略 {args.strategy}｜再平衡 {args.rebalance}")
    print("取历史日线并逐标的回测…")
    try:
        res = run_portfolio(specs, strategy=args.strategy, params=params,
                            rebalance=args.rebalance, start=args.start, end=args.end)
    except ValueError as e:
        print(f"无法回测：{e}")
        return 2

    m, bm = res.metrics, res.benchmark_metrics
    print(f"\n公共区间：{res.start} ~ {res.end}（{m['bars']} 个交易日）")
    print("目标权重：" + " / ".join(f"{t} {w*100:.1f}%" for t, w in res.weights.items()))
    print("\n" + "=" * 66)
    print(f"{'指标':<14}{'策略组合':>14}{'buy_hold基准':>14}{'超额':>12}")
    rows = [
        ("总收益率(%)", m["total_return_pct"], bm["total_return_pct"], m["excess_return_pct"]),
        ("年化收益(%)", m["annual_return_pct"], bm["annual_return_pct"],
         round(m["annual_return_pct"] - bm["annual_return_pct"], 2)),
        ("年化波动(%)", "—", bm["volatility_pct"], None),
        ("最大回撤(%)", m["max_drawdown_pct"], bm["max_drawdown_pct"], None),
        ("夏普比率", m["sharpe"], bm["sharpe"], round(m["sharpe"] - bm["sharpe"], 3)),
    ]
    for name, a, b, d in rows:
        ds = f"{d:+.2f}" if d is not None else "—"
        print(f"{name:<14}{str(a):>14}{str(b):>14}{ds:>12}")
    print("=" * 66)

    print("\n各标的贡献（公共区间内，各自策略表现）：")
    print(f"{'标的':<10}{'权重%':>7}{'年化%':>8}{'波动%':>8}{'回撤%':>8}{'夏普':>7}{'买入持有%':>11}")
    for h in res.holdings:
        print(f"{h['ticker']:<10}{h['weight_pct']:>7.1f}{h['annual_return_pct']:>8}"
              f"{h['volatility_pct']:>8}{h['max_drawdown_pct']:>8}{h['sharpe']:>7}"
              f"{h['buy_hold_pct']:>11}")

    print(f"\n{DISCLAIMER}")
    print("简化：v1 不计再平衡层换手费（标的层费用已计），权重不做风险平价。")

    out_dir = DATA_DIR / "portfolio"
    out_dir.mkdir(parents=True, exist_ok=True)
    tag = "_".join(tickers[:4])
    path = out_dir / f"{tag}_{args.strategy}_{now_cn():%Y%m%d_%H%M%S}.json"
    payload = {"tickers": tickers, "weights": res.weights, "strategy": res.strategy,
               "params": res.params, "rebalance": res.rebalance,
               "start": res.start, "end": res.end,
               "metrics": m, "benchmark_metrics": bm, "holdings": res.holdings,
               "equity": res.equity.reset_index().rename(columns={"index": "date"}).to_dict("records")}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"结果已保存：{path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
