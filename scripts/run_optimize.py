# -*- coding: utf-8 -*-
"""策略参数寻优 CLI：网格批量回测 + 绩效平原 + Walk-forward 跨期验证。

用法：
  run_optimize.py SH510300 --strategy ma_cross --fast 3,5,10 --slow 20,30,60
  run_optimize.py SH600519 --strategy rsi_reversion --objective sharpe
      （不传任何参数候选时用内置默认网格）
  run_optimize.py 0700.HK --strategy macd_cross --split 0.6

参数候选以逗号分隔的数字列表逐个传入（仅识别该策略 STRATEGY_META 中登记的参数名）。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.config import DATA_DIR, DISCLAIMER, now_cn, setup_logging
from core.data import service
from core.optimize import grid as opt
from core.quant.backtest import STRATEGY_META, BacktestConfig


def _parse_grid(args, strategy: str) -> dict[str, list] | None:
    """从 CLI 参数收集 {参数名: [候选值]}；一个都没传则返回 None（用默认网格）。"""
    names = [p[0] for p in STRATEGY_META[strategy]["params"]]
    spec: dict[str, list] = {}
    for name in names:
        raw = getattr(args, name, None)
        if raw:
            vals = []
            for tok in raw.split(","):
                tok = tok.strip()
                if tok:
                    vals.append(int(float(tok)))
            if vals:
                spec[name] = sorted(set(vals))
    return spec or None


def main() -> int:
    ap = argparse.ArgumentParser(description="StockAIPredictor 策略参数寻优")
    ap.add_argument("ticker")
    ap.add_argument("--strategy", default="rsi_reversion",
                    choices=["rsi_reversion", "ma_cross", "macd_cross"])
    ap.add_argument("--objective", default="sharpe",
                    choices=list(opt.OBJECTIVES), help="寻优目标（默认 sharpe）")
    ap.add_argument("--split", type=float, default=0.6, help="walk-forward 样本内比例（默认0.6）")
    ap.add_argument("--start", default=None)
    ap.add_argument("--end", default=None)
    # 三个策略的全部参数（未用到的留空）
    ap.add_argument("--rsi_period", default=None, help="如 7,14,21")
    ap.add_argument("--buy_thr", default=None, help="如 20,25,30")
    ap.add_argument("--sell_thr", default=None, help="如 65,70,75")
    ap.add_argument("--fast", default=None, help="短均线候选，如 3,5,10")
    ap.add_argument("--slow", default=None, help="长均线候选，如 20,30,60")
    ap.add_argument("--macd_fast", default=None)
    ap.add_argument("--macd_slow", default=None)
    ap.add_argument("--macd_signal", default=None)
    args = ap.parse_args()

    setup_logging()
    ticker = args.ticker.upper()
    market = service.market_of(ticker)
    if market == "UNKNOWN":
        print(f"无法识别标的: {ticker}")
        return 2

    spec = _parse_grid(args, args.strategy) or opt.DEFAULT_GRIDS[args.strategy]
    n_combos = 1
    for v in spec.values():
        n_combos *= len(v)
    print(f"标的 {ticker}（{market}）策略 {args.strategy} 目标 {opt.OBJECTIVE_LABELS[args.objective]}")
    print(f"参数网格 {spec} → {n_combos} 个组合，取历史日线…")
    if n_combos > opt.MAX_COMBOS:
        print(f"组合数超上限 {opt.MAX_COMBOS}，请缩小网格")
        return 2

    bars, status = service.get_daily(ticker)
    print(f"数据 {status}，{len(bars)} 根（{bars.index[0].date()}~{bars.index[-1].date()}）\n")

    cfg = BacktestConfig(ticker=ticker, market=market, start=args.start, end=args.end)

    def cb(stage, i, total):
        label = {"grid": "网格回测", "plateau": "平原评估", "walkforward": "跨期验证"}.get(stage, stage)
        if stage == "grid":
            print(f"\r{label} {i}/{total}...", end="", flush=True)
        else:
            print(f"\n{label}完成")

    try:
        out = opt.optimize(bars, market, args.strategy, spec, cfg,
                          objective=args.objective, split=args.split, progress_cb=cb)
    except ValueError as e:
        print(f"\n无法寻优：{e}")
        return 2

    # ---- 输出 ----
    print("\n" + "=" * 78)
    print(f"TOP 15 / {out['n_combos']} 组合（按 {out['objective_label']} 降序，未交易排末尾）")
    print("-" * 78)
    print(f"{'排名':>3} {'参数':<34} {'目标':>8} {'年化%':>7} {'回撤%':>7} {'夏普':>6} {'胜率%':>6} {'笔数':>4}")
    for rk, r in enumerate(out["results"][:15], 1):
        m = r["metrics"]
        mark = "" if r["traded"] else "  (无交易)"
        print(f"{rk:>3} {str(r['params']):<34} {r['objective']:>8} "
              f"{m['annual_return_pct']:>7} {m['max_drawdown_pct']:>7} {m['sharpe']:>6} "
              f"{m['win_rate_pct']:>6} {m['trade_count']:>4}{mark}")

    best = out["best"]
    print("\n" + "=" * 78)
    print(f"最优参数：{best['params']}")
    print(f"  目标值 {best['objective']}｜年化 {best['metrics']['annual_return_pct']}%｜"
          f"最大回撤 {best['metrics']['max_drawdown_pct']}%｜夏普 {best['metrics']['sharpe']}｜"
          f"胜率 {best['metrics']['win_rate_pct']}%")
    p = out["plateau"]
    print(f"平原评估：{p['rating']}" + (f"（robust={p['robust']}，容忍带±{p['tol']}）" if p['robust'] is not None else ""))
    for nb in p.get("neighbors", []):
        print(f"    邻居 {nb['params']} → {nb['objective']}" + (" 同质" if nb["within_tol"] else " 塌陷"))

    wf = out["walk_forward"]
    print("-" * 78)
    print(f"Walk-forward（IS 截止 {wf['split_date']}，IS {wf['is_bars']}根 / OOS {wf['oos_bars']}根）")
    print(f"  IS 选参：{wf['is_best_params']}（目标 {wf['is_objective']}）")
    print(f"  该参数 OOS：目标 {wf['oos_objective_of_is_best']}，"
          f"年化 {wf['oos_metrics_of_is_best']['annual_return_pct']}%，"
          f"回撤 {wf['oos_metrics_of_is_best']['max_drawdown_pct']}%")
    print(f"  OOS 排名分位 {wf['oos_percentile']}（1=事后最优）｜{wf['rating']}")
    print("=" * 78)
    print(DISCLAIMER)
    print("提示：网格+单区间寻优天然高估，务必以平原评级与 OOS 分位为准；孤立尖峰参数不可用于实盘。")

    out_dir = DATA_DIR / "optimize"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{ticker}_{args.strategy}_{now_cn():%Y%m%d_%H%M%S}.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"结果已保存：{path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
