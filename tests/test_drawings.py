# -*- coding: utf-8 -*-
"""K线绘图工具测试：持久化存储 + 四件套渲染 + Agent get_drawings 工具。

运行：venv\Scripts\python.exe tests\test_drawings.py
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("STOCKAI_MOCK", "1")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main() -> int:
    import numpy as np
    import pandas as pd

    from core.drawings import (clear_ticker, delete_drawing,
                               list_drawings, save_drawing)

    T = "SH600519"
    clear_ticker(T)

    # 1) 存储层：保存/读取/删除/清空（x 用全局索引，落在渲染窗口内）
    i1 = save_drawing(T, "trend", [{"x": 255, "y": 100.0}, {"x": 290, "y": 110.0}])
    i2 = save_drawing(T, "hlevel", [{"x": 260, "y": 105.0}])
    i3 = save_drawing(T, "fib", [{"x": 255, "y": 120.0}, {"x": 280, "y": 90.0}],
                      {"levels": [0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0]})
    i4 = save_drawing(T, "rect", [{"x": 252, "y": 90.0}, {"x": 262, "y": 110.0}])
    assert i1 and i2 and i3 and i4, "保存失败"
    draws = list_drawings(T)
    assert len(draws) == 4 and draws[0]["type"] == "trend", draws
    assert draws[2]["meta"]["levels"] == [0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0]
    assert delete_drawing(i4) and len(list_drawings(T)) == 3
    print(f"[ok] 存储层 4 类型 增删查")

    # 2) 渲染层：四种工具在 offscreen ChartTab 上生成正确 item
    from PyQt6.QtWidgets import QApplication
    from app.ui.chart_tab import ChartTab

    app = QApplication.instance() or QApplication([])
    tab = ChartTab()
    rng = np.random.default_rng(7)
    n = 300
    dates = pd.bdate_range("2023-01-02", periods=n)
    close = 100 + np.cumsum(rng.normal(0, 1, n))
    open_ = close + rng.normal(0, 0.3, n)
    df = pd.DataFrame({"open": open_, "high": np.maximum(open_, close) + 0.5,
                       "low": np.minimum(open_, close) - 0.5,
                       "close": close, "volume": rng.integers(1e5, 1e6, n).astype(float)},
                      index=dates)
    tab._bars = df
    tab._ticker = T
    tab._redraw()

    # trend: 2 点 → 1 InfiniteLine（x 为全局索引，落在当前窗口 250 根内）
    items = tab._render_drawing("trend", [{"x": 255, "y": 100.0}, {"x": 290, "y": 110.0}], {})
    assert len(items) == 1 and isinstance(items[0], __import__("pyqtgraph").InfiniteLine), items
    # hlevel: 1 点 → 线 + 标签
    items = tab._render_drawing("hlevel", [{"x": 260, "y": 105.0}], {})
    assert len(items) == 2, items
    # fib: 2 点 → 7 线 + 7 标签
    items = tab._render_drawing("fib", [{"x": 255, "y": 120.0}, {"x": 280, "y": 90.0}],
                                {"levels": [0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0]})
    assert len(items) == 14, len(items)
    # rect: 2 点 → 1 ROI
    items = tab._render_drawing("rect", [{"x": 252, "y": 90.0}, {"x": 262, "y": 110.0}], {})
    assert len(items) == 1, items
    # 越界整条跳过
    items = tab._render_drawing("hlevel", [{"x": 9999, "y": 100.0}], {})
    assert items == []
    print("[ok] 渲染层 四件套 + 越界跳过")

    # 3) 恢复渲染
    tab._restore_drawings()
    assert len(tab._drawing_items) == 3, len(tab._drawing_items)
    print("[ok] 持久化恢复渲染")

    # 4) Agent 工具联动：get_drawings 返回日期+价格
    from agent.tool_defs import call_tool
    res = call_tool("get_drawings", {"code": T})
    assert res.ok, res
    assert len(res.data["drawings"]) == 3, res.data
    first = res.data["drawings"][0]
    assert first["type"] == "trend" and first["points"][0]["date"].startswith("20"), first
    print("[ok] Agent get_drawings 工具")

    clear_ticker(T)
    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
