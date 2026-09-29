# -*- coding: utf-8 -*-
"""Agent 工具调用层冒烟测试：意图解析 + 工具链 + 合规 + 记忆写入。

运行：venv\Scripts\python.exe tests\test_agent_core.py
（内部使用 mock 环境，不依赖网络与 API Key）
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("STOCKAI_MOCK", "1")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main() -> int:
    from agent import AgentCore, extract_ticker
    from agent.mcp_server import _tool_schemas

    c = AgentCore()

    cases = [
        ("分析 茅台", ["fetch_stock_data", "calculate_indicators"]),
        ("茅台最近有什么新闻", ["search_news"]),
        ("回测 600519 ma_cross", ["run_backtest"]),
        ("今天大盘怎么样", ["get_market_overview"]),
        ("gzmt 全面分析", ["fetch_stock_data", "calculate_indicators", "search_news"]),
        ("看看腾讯的实时价格", ["get_realtime_snapshot"]),
        ("搜索 银行", ["search_stocks"]),
        ("筛选 市盈率低于15的银行股", ["run_screener"]),
    ]
    for text, want in cases:
        plan = c.run(text)["plan"]
        got = [p["tool"] for p in plan]
        assert got == want, f"{text}: got {got}, want {want}"
        print(f"[ok] {text} -> {got}")

    # 别名/代码提取
    assert extract_ticker("分析 茅台") == "SH600519"
    assert extract_ticker("gzmt 全面分析") == "SH600519"
    assert extract_ticker("600519") == "SH600519"
    assert extract_ticker("0700.HK") == "0700.HK"
    assert extract_ticker("AAPL") == "AAPL"
    print("[ok] extract_ticker 别名/代码")

    # 合规过滤：输出若含红线话术应被标注
    r = c.run("回测 600519 ma_cross")
    assert r["answer"], "回测应有输出"
    assert "不构成投资建议" in r["answer"], "输出须含合规声明"
    print("[ok] 合规声明")

    # 记忆写入：审计链应新增记录
    from security.audit_ledger import records
    recs = records(limit=5)
    assert any(x["action"] == "agent_analysis" for x in recs), "审计链应有 agent 记录"
    print("[ok] 审计链写入")

    # MCP 工具清单
    schemas = _tool_schemas()
    names = {s["name"] for s in schemas}
    assert {"fetch_stock_data", "run_backtest", "search_stocks"} <= names
    print(f"[ok] MCP 工具清单 {len(schemas)} 个")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
