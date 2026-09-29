# -*- coding: utf-8 -*-
"""回测严谨性审计测试：前视偏差扫描 + Walk-Forward。

运行：venv\Scripts\python.exe tests\test_quant_audit.py
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

    from core.quant.audit import run_audit, scan_lookahead, walk_forward
    from core.quant.backtest import BacktestConfig

    # 构造 500 根确定性 OHLCV 日线（无未来依赖）
    rng = np.random.default_rng(42)
    n = 500
    dates = pd.bdate_range("2022-01-03", periods=n)
    close = 100 + np.cumsum(rng.normal(0, 1, n))
    close = np.clip(close, 20, None)
    open_ = close + rng.normal(0, 0.4, n)
    high = np.maximum(open_, close) + np.abs(rng.normal(0, 0.5, n))
    low = np.minimum(open_, close) - np.abs(rng.normal(0, 0.5, n))
    vol = rng.integers(100_000, 1_000_000, n).astype(float)
    df = pd.DataFrame({"open": open_, "high": high, "low": low,
                       "close": close, "volume": vol, "chg_pct": 0.0},
                      index=dates)

    cfg = BacktestConfig(market="CN", ticker="SH600000")

    # 1) 前视偏差：正确实现的策略应 pass
    la = scan_lookahead(df, "ma_cross", {"fast": 5, "slow": 20})
    print("lookahead ma_cross:", la["verdict"], f"({la['checked']} 点 / {la['mismatches']} 偏移)")
    assert la["verdict"] == "pass", la

    # 2) Walk-Forward 结构完整
    wf = walk_forward(df, "CN", "ma_cross", {"fast": 5, "slow": 20}, cfg)
    assert "error" not in wf, wf
    assert set(wf["in"]) == set(wf["out"]) == set(wf["full"])
    assert "total_return_pct" in wf["in"]
    print("walk_forward 切分点:", wf["split_date"], "样本内", wf["in_bars"], "样本外", wf["out_bars"])

    # 3) 一站式审计
    audit = run_audit(df, "CN", "ma_cross", {"fast": 5, "slow": 20}, cfg)
    assert audit["lookahead"]["verdict"] in ("pass", "suspect", "fail", "na")
    assert "walk_forward" in audit
    print("audit ok:", audit["lookahead"]["verdict"])

    # 4) buy_hold 不适用
    la_bh = scan_lookahead(df, "buy_hold", {})
    assert la_bh["verdict"] == "na", la_bh
    print("buy_hold lookahead:", la_bh["verdict"])

    # 5) 数据不足降级
    wf_small = walk_forward(df.iloc[:80], "CN", "ma_cross", {"fast": 5, "slow": 20}, cfg)
    assert "error" in wf_small
    print("short-data:", wf_small["error"][:20])

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
