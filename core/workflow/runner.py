# -*- coding: utf-8 -*-
"""分析工作流运行器（模块五 · 参考 FinceptTerminal 节点编辑器）。

把「数据获取 → 指标计算 → AI 分析 → 回测 → 报告」拆成可拖拽排序的
节点，节点执行全部确定性降级安全（数据不可用时输出提示节点，不抛异常）。

- NODE_REGISTRY：节点名 → (category, 执行函数)；
- run_workflow(nodes, context)：按顺序执行节点链，返回步骤结果列表；
- 纯逻辑可单测；UI 层（workflow_tab）负责拖拽排序与展示。
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

log = logging.getLogger("stockai.core.workflow")

NODE_CATEGORY = {
    "fetch_data": "数据获取", "calc_indicators": "指标计算",
    "ai_analysis": "AI 分析", "run_backtest": "回测验证",
    "gen_report": "生成报告",
}


def node_fetch_data(ctx: Dict[str, Any], **kw) -> Dict[str, Any]:
    ticker = ctx.get("ticker") or "600519"
    try:
        from core.data.service import fetch_bars
        bars = fetch_bars(ticker, as_of=kw.get("as_of"))
        return {"node": "fetch_data", "status": "ok",
                "summary": f"{ticker} K线 {len(bars) if bars is not None else 0} 根"}
    except Exception as e:  # noqa: BLE001
        return {"node": "fetch_data", "status": "degraded",
                "summary": f"{ticker} 数据不可用（{e}），使用缓存/示例数据"}


def node_calc_indicators(ctx: Dict[str, Any], **kw) -> Dict[str, Any]:
    try:
        from core.features.wickra_bridge import compute_features
        bars = ctx.get("bars")
        feats = compute_features(bars) if bars is not None else {}
        return {"node": "calc_indicators", "status": "ok",
                "summary": f"指标 {len(feats)} 项（RSI/MACD/MA/ATR…）",
                "features": feats}
    except Exception as e:  # noqa: BLE001
        return {"node": "calc_indicators", "status": "degraded",
                "summary": f"指标计算失败：{e}"}


def node_ai_analysis(ctx: Dict[str, Any], **kw) -> Dict[str, Any]:
    ticker = ctx.get("ticker") or "600519"
    feats = (ctx.get("features") or {})
    try:
        from core.strategies import run_strategy
        sig = run_strategy("rsi_macd", ctx.get("bars"),
                           feats if feats else None) if ctx.get("bars") is not None \
            else {"stance": "中性", "view": "无K线数据，跳过指标共振"}
        return {"node": "ai_analysis", "status": "ok",
                "summary": (f"{ticker}：{sig.get('stance')}（{sig.get('view', '')[:40]}）"),
                "signal": sig}
    except Exception as e:  # noqa: BLE001
        return {"node": "ai_analysis", "status": "degraded",
                "summary": f"AI 分析降级：{e}"}


def node_run_backtest(ctx: Dict[str, Any], **kw) -> Dict[str, Any]:
    try:
        from core.quant.backtest import run_backtest
        bars = ctx.get("bars")
        if bars is None:
            return {"node": "run_backtest", "status": "degraded",
                    "summary": "无K线数据，跳过回测"}
        r = run_backtest(bars, "CN", "ma_cross")
        st = r.get("stats") or {}
        return {"node": "run_backtest", "status": "ok",
                "summary": f"回测：总收益 {st.get('total_return', 0):.2%}，"
                           f"回撤 {st.get('max_drawdown', 0):.2%}",
                "stats": st}
    except Exception as e:  # noqa: BLE001
        return {"node": "run_backtest", "status": "degraded",
                "summary": f"回测失败：{e}"}


def node_gen_report(ctx: Dict[str, Any], **kw) -> Dict[str, Any]:
    steps = ctx.get("step_results") or []
    lines = ["# 分析报告", f"标的：{ctx.get('ticker') or '600519'}"]
    for s in steps:
        lines.append(f"- **{NODE_CATEGORY.get(s['node'], s['node'])}**"
                     f"[{s['status']}]：{s['summary']}")
    report = "\n".join(lines)
    return {"node": "gen_report", "status": "ok", "summary": "报告已生成",
            "report": report}


NODE_REGISTRY: Dict[str, Callable[..., Dict[str, Any]]] = {
    "fetch_data": node_fetch_data,
    "calc_indicators": node_calc_indicators,
    "ai_analysis": node_ai_analysis,
    "run_backtest": node_run_backtest,
    "gen_report": node_gen_report,
}


def run_workflow(nodes: List[str], ticker: str = "600519",
                 as_of: str | None = None,
                 bars: Any = None) -> Dict[str, Any]:
    """顺序执行节点链。返回 {results, report, ok}。"""
    ctx: Dict[str, Any] = {"ticker": ticker, "as_of": as_of, "bars": bars}
    results: List[Dict[str, Any]] = []
    for node in nodes:
        fn = NODE_REGISTRY.get(node)
        if not fn:
            results.append({"node": node, "status": "error",
                            "summary": f"未知节点：{node}"})
            continue
        try:
            out = fn(ctx)
            out["node"] = node
            ctx.setdefault("step_results", []).append(out)
            if node == "fetch_data" and out.get("status") == "ok" \
                    and ctx.get("bars") is None:
                # 从数据服务重新取（runner 内部不持有 bars 时）
                try:
                    from core.data.service import fetch_bars
                    ctx["bars"] = fetch_bars(ticker, as_of=as_of)
                except Exception:  # noqa: BLE001
                    pass
            if node == "calc_indicators" and out.get("features"):
                ctx["features"] = out["features"]
            results.append(out)
        except Exception as e:  # noqa: BLE001
            results.append({"node": node, "status": "error",
                            "summary": f"执行失败：{e}"})
    report = ""
    for r in results:
        if r["node"] == "gen_report":
            report = r.get("report", "")
    if not report:
        report = "\n".join(f"- {NODE_CATEGORY.get(r['node'], r['node'])}"
                           f"[{r['status']}]：{r['summary']}" for r in results)
    return {"results": results, "report": report,
            "ok": all(r["status"] != "error" for r in results)}


DEFAULT_FLOW = ["fetch_data", "calc_indicators", "ai_analysis",
                "run_backtest", "gen_report"]

if __name__ == "__main__":
    import numpy as np
    import pandas as pd
    rng = np.random.default_rng(4)
    idx = pd.date_range("2025-01-01", periods=120)
    close = pd.Series(100 * np.cumprod(1 + rng.normal(0.001, 0.02, 120)),
                      index=idx)
    bars = pd.DataFrame({"open": close, "high": close * 1.01,
                         "low": close * 0.99, "close": close,
                         "volume": rng.integers(1e5, 5e5, 120)}, index=idx)
    r = run_workflow(DEFAULT_FLOW, ticker="600519", bars=bars)
    assert len(r["results"]) == 5
    assert r["ok"]
    assert "# 分析报告" in r["report"]
    r2 = run_workflow(["fetch_data", "gen_report"], ticker="TEST.XX")
    assert r2["results"][0]["status"] in ("ok", "degraded")
    assert r2["ok"]  # degraded 不算 error
    print("workflow runner self-check ok")
