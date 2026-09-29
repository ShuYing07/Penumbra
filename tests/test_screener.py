# -*- coding: utf-8 -*-
"""结构化 Screener 测试：引擎离线降级 + 股票大全面板 + Agent 联动。

运行：venv\Scripts\python.exe tests\test_screener.py
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("STOCKAI_MOCK", "1")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main() -> int:
    from core.screener import run_screener

    # 1) 市场过滤（离线，索引级）
    r = run_screener(market="A股", limit=5)
    assert r["ok"] and len(r["hits"]) == 5
    assert all(h["market"] == "A股" for h in r["hits"]), r
    print("[ok] 市场过滤")

    # 2) 上市板块过滤
    r = run_screener(market="A股", board="创业板", limit=20)
    assert r["ok"] and r["hits"] and all(h["board"] == "创业板" for h in r["hits"]), r
    print(f"[ok] 上市板块过滤（{len(r['hits'])} 只创业板）")

    # 3) 行业过滤（离线 → 数据源不可达，正确降级并标注）
    r = run_screener(market="A股", board="银行", limit=5)
    assert r["ok"], r
    assert any("不可达" in n or "已跳过" in n for n in [r["note"]]), r["note"]
    print("[ok] 行业降级标注")

    # 4) 价格/涨跌幅条件（离线无实时 → A股保留代码级结果 + 说明）
    r = run_screener(market="A股", price_min=10, price_max=50, chg_min=-5, chg_max=5, limit=10)
    assert r["ok"] and r["hits"], r
    print("[ok] 数值条件离线降级")

    # 5) Agent 联动：自然语言 → run_screener 工具（离线 mock）
    from agent import AgentCore
    core = AgentCore()
    plan = core.run("筛选 市盈率低于15的银行股")["plan"]
    assert any(p["tool"] == "run_screener" for p in plan), plan
    res = core.run("筛选 银行板块价格低于50的股票")
    got = [p["tool"] for p in res["plan"]]
    assert got == ["run_screener"], got
    print("[ok] Agent NL→筛选工具链")

    # 6) 股票大全 UI：信号与筛选按钮存在
    from PyQt6.QtWidgets import QApplication
    from app.ui.stock_directory_tab import StockDirectoryTab
    app = QApplication.instance() or QApplication([])
    tab = StockDirectoryTab()
    assert hasattr(tab, "add_watchlist"), "add_watchlist 信号缺失"
    assert hasattr(tab, "_run_screener") and hasattr(tab, "sp_price_min")
    print("[ok] 股票大全筛选面板与信号")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
