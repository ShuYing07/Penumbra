# -*- coding: utf-8 -*-
"""一期 CLI 入口：对标的执行完整多智能体分析并生成 Markdown 报告。

示例：
  venv\\Scripts\\python.exe run_analysis.py SH600519 AAPL BTC-USD
  venv\\Scripts\\python.exe run_analysis.py AAPL --mock      # 离线演示（不调用 DeepSeek）
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def main() -> int:
    parser = argparse.ArgumentParser(description="StockAIPredictor 多智能体分析")
    parser.add_argument("tickers", nargs="*", default=["SH600519", "AAPL", "BTC-USD"],
                        help="标的代码，默认 SH600519 AAPL BTC-USD")
    parser.add_argument("--mock", action="store_true", help="离线桩模式，不调用任何大模型")
    parser.add_argument("--model", default=None, help="覆盖云端模型（默认 deepseek-flash）")
    parser.add_argument("--backend", choices=["deepseek", "local", "auto"], default=None,
                        help="引擎：deepseek 云端 / local 本地离线 / auto 云端失败自动切本地")
    parser.add_argument("--local-model", default=None,
                        help="本地模型标签（默认 qwen2.5:7b-instruct-q4_K_M）")
    parser.add_argument("--paper", action="store_true", help="买入/卖出建议自动落入模拟盘")
    args = parser.parse_args()

    if args.mock:
        os.environ["STOCKAI_MOCK"] = "1"
    if args.backend:
        os.environ["STOCKAI_LLM_BACKEND"] = args.backend
    if args.local_model:
        os.environ["STOCKAI_LOCAL_MODEL"] = args.local_model

    # 在导入 core 之前设好环境
    from core.agents.graph import run_analysis
    from core.config import REPORT_DIR, ensure_utf8_stdio, setup_logging
    from core.data import cache
    from core.llm import LLMRunner
    from core.memory.reflection import evaluate_pending
    from core.report import render

    ensure_utf8_stdio()
    logger = setup_logging()
    cache.init_db()

    runner = (LLMRunner(model=args.model) if args.model
              else LLMRunner(backend=args.backend or "deepseek",
                             local_model=args.local_model))
    mode = ("离线MOCK" if runner.mock else
            {"deepseek": "DeepSeek云端", "local": "本地模型(离线)",
             "auto": "自动切换"}.get(runner.backend, runner.backend))
    logger.info("LLM 模式：%s", mode)

    try:
        evaled = evaluate_pending(limit=10)
        if evaled:
            logger.info("决策复盘：已评估 %d 条到期决策（已写偏好标签）", len(evaled))
    except Exception as e:  # noqa: BLE001
        logger.warning("决策复盘跳过：%s", e)

    exit_code = 0
    for ticker in args.tickers:
        try:
            logger.info("=" * 60)
            logger.info("开始分析 %s", ticker)
            result = run_analysis(ticker, runner=runner)
            state = result["state"]
            if args.paper:
                from core.portfolio import paper
                state["_decision_id"] = result.get("decision_id")
                trade = paper.execute(state)
                if trade:
                    logger.info("💰 模拟盘：%s %s %s股 @ %s",
                                trade["side"], trade["ticker"], trade["shares"], trade["price"])
            md = render(state)
            out = REPORT_DIR / f"{ticker}_{state.get('asof', '')}.md"
            out.write_text(md, encoding="utf-8")
            final = state.get("final", {})
            logger.info("✅ %s 完成：%s 仓位%s%% → 报告 %s",
                        ticker, final.get("action"), final.get("position_pct"), out)
            if state.get("errors"):
                logger.warning("过程降级节点：%s", "; ".join(state["errors"]))
        except Exception as e:  # noqa: BLE001
            exit_code = 1
            logger.exception("❌ %s 分析失败：%s", ticker, e)
    logger.info("全部结束。累计：%s", runner.usage())
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
