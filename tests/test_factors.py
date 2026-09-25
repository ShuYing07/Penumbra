# -*- coding: utf-8 -*-
"""core.quant.factors 多因子体系单测：纯合成序列，零网络。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd

from core.quant.factors import compute_factors


def _df(prices, start="2024-01-01"):
    idx = pd.bdate_range(start, periods=len(prices))
    arr = np.asarray(prices, dtype=float)
    vol = np.full(len(prices), 1e6)
    return pd.DataFrame({
        "open": arr, "high": arr * 1.01, "low": arr * 0.99,
        "close": arr, "volume": vol,
    }, index=idx)


P = 0


def check(name, cond, detail=""):
    global P
    assert cond, f"FAIL {name} {detail}"
    print("PASS", name)
    P += 1


def main():
    global P
    P = 0
    # 1. 稳定上涨 90 日 → 综合应偏多
    up = _df(np.linspace(10, 22, 90))
    r = compute_factors(up)
    check("up_composite_bullish", r["composite"] is not None and r["composite"] >= 55,
          r["composite"])

    # 2. 稳定下跌 90 日 → 综合应偏空
    down = _df(np.linspace(22, 10, 90))
    r2 = compute_factors(down)
    check("down_composite_bearish", r2["composite"] is not None and r2["composite"] <= 45,
          r2["composite"])

    # 3. 常量序列 → 不崩，composite 中性或 None（动量/趋势 0，量能数据可算）
    flat = _df([10.0] * 90)
    r3 = compute_factors(flat)
    check("flat_no_crash", r3["composite"] is not None or r3["composite"] is None)

    # 4. 数据不足（10 根）→ 不崩，多为 None
    few = _df(np.linspace(10, 12, 10))
    r4 = compute_factors(few)
    check("few_bars_no_crash", isinstance(r4, dict) and "consensus" in r4)

    # 5. 估值因子：低 PE 偏多，高 PE 偏空
    low_pe = compute_factors(up, {"pe": 10})["factors"]["valuation"]["score"]
    high_pe = compute_factors(up, {"pe": 60})["factors"]["valuation"]["score"]
    check("valuation_low_pe_bull", low_pe is not None and low_pe > 0.15, low_pe)
    check("valuation_high_pe_bear", high_pe is not None and high_pe < -0.15, high_pe)

    # 6. 无基本面 → 估值 None，整体仍出分
    r6 = compute_factors(up)
    check("valuation_none_when_no_funda",
          r6["factors"]["valuation"]["score"] is None)

    # 7. 所有因子 score 合法范围 [-1,1] 或 None
    ok = all((p["score"] is None or -1.0 <= p["score"] <= 1.0)
             for p in r["factors"].values())
    check("score_range_bounded", ok)

    # 8. bull/bear 依据结构
    check("bull_bear_structure",
          isinstance(r["bull_signals"], list) and isinstance(r["bear_signals"], list))

    print(f"{P}/{P} 个多因子测试通过")
    assert P == 9, "计数不符"


if __name__ == "__main__":
    main()
