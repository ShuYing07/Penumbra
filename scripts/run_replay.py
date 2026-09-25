# -*- coding: utf-8 -*-
"""AI 信号历史回放 CLI：在历史多个时点跑 AI 管线，用 t+5/10/20 真实走势评估。

用法：
  venv\\Scripts\\python.exe scripts\\run_replay.py SH600519
  run_replay.py 0700.HK --start 2024-01-01 --end 2025-06-30 --step 40
  run_replay.py SH600519 --engine deepseek   # 真实 LLM（按 token 计费）

默认 mock 引擎（离线规则桩，零成本，信号非真实 AI 推理，仅验证回放链路/规则有效性）。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.config import DATA_DIR, DISCLAIMER, setup_logging
from core.data import service
from core.replay import engine, store


def _print_stats(st: dict) -> None:
    d = st["distribution"]
    print("\n" + "=" * 60)
    print(f"批次 {st['batch_id']}：样本 {st['n']}  "
          f"多 {d['多']} / 空 {d['空']} / 中性 {d['中性']} / 错误 {d['错误']}")
    print("-" * 60)
    print(f"{'持有期':>6} {'已评估':>6} {'方向样本':>8} {'方向胜率':>8} "
          f"{'平均收益':>8} {'多头均收':>8} {'空头均收':>8}")
    for h, s in st["horizons"].items():
        def fmt(v):
            return f"{v:+.2f}%" if v is not None else "—"
        wr = f"{s['win_rate_pct']}%" if s["win_rate_pct"] is not None else "—"
        print(f"{str(h) + '日':>6} {s['evaluated']:>6} {s['directional']:>8} "
              f"{wr:>8} {fmt(s['avg_ret_pct']):>8} "
              f"{fmt(s['long_avg_pct']):>8} {fmt(s['short_avg_pct']):>8}")
    print("=" * 60)


def main() -> int:
    ap = argparse.ArgumentParser(description="StockAIPredictor AI 信号历史回放")
    ap.add_argument("ticker", help="标的，如 SH600519 / 0700.HK / SH510300")
    ap.add_argument("--start", default=None, help="回放起点 YYYY-MM-DD（默认数据首日+预热）")
    ap.add_argument("--end", default=None, help="回放终点 YYYY-MM-DD（默认数据末日前20交易日）")
    ap.add_argument("--step", type=int, default=20, help="取样步长（交易日，默认20≈月度）")
    ap.add_argument("--engine", default="mock", choices=["mock", "deepseek", "local"],
                    help="推理引擎（默认 mock 离线规则桩，零成本）")
    args = ap.parse_args()

    setup_logging()
    store.init()
    ticker = args.ticker.upper()
    market = service.market_of(ticker)
    if market == "UNKNOWN":
        print(f"无法识别标的: {ticker}")
        return 2

    print(f"标的 {ticker}（市场 {market}）引擎 {args.engine}，取历史日线…")
    if args.engine != "mock":
        print("⚠️ 真实 LLM 回放按 token 计费，每个回放点跑完整 8 节点。")

    def progress(n, total, asof):
        print(f"  回放进度 [{n}/{total}] {asof}", flush=True)

    try:
        batch_id = engine.run_replay(
            ticker, start=args.start, end=args.end,
            step_bars=args.step, engine=args.engine, progress_cb=progress)
    except ValueError as e:
        print(f"无法回放：{e}")
        return 2

    rows = store.list_batch(batch_id)
    print(f"\n{'时点':>12} {'动作':<6} {'仓位':>4} {'当时价':>10} "
          f"{'5日':>8} {'10日':>8} {'20日':>8} {'命中10日':>8}")
    for r in rows:
        if r["error"]:
            print(f"{r['asof']:>12} 错误：{r['error'][:40]}")
            continue
        def fmt(v):
            return f"{v:+.2f}%" if v is not None else "—"
        hit = {1: "✓", 0: "✗", None: "·"}.get(r["hit_10"], "·")
        print(f"{r['asof']:>12} {r['action'] or '':<6} {r['position_pct'] or 0:>4} "
              f"{r['price'] or 0:>10.4g} {fmt(r['ret_5']):>8} "
              f"{fmt(r['ret_10']):>8} {fmt(r['ret_20']):>8} {hit:>8}")

    st = engine.batch_stats(batch_id)
    _print_stats(st)

    out_dir = DATA_DIR / "replay"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{batch_id}.json"
    out_path.write_text(json.dumps(
        {"stats": st, "rows": [{k: v for k, v in r.items() if k != "final_json"}
                                for r in rows]},
        ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"结果已保存：{out_path}")
    print(f"\n{DISCLAIMER}")
    if args.engine == "mock":
        print("注意：mock 引擎信号为离线规则桩生成，不代表真实 AI 推理能力。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
