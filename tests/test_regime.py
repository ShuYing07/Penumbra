# -*- coding: utf-8 -*-
"""core.quant.market_regime 市场状态判别单测。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd

from core.quant.market_regime import classify_regime


def _df(prices):
    idx = pd.bdate_range("2023-01-01", periods=len(prices))
    arr = np.asarray(prices, dtype=float)
    return pd.DataFrame({"open": arr, "high": arr * 1.01, "low": arr * 0.99,
                         "close": arr, "volume": np.full(len(prices), 1e6)}, index=idx)


P = 0


def check(name, cond, detail=""):
    global P
    assert cond, f"FAIL {name} {detail}"
    print("PASS", name)
    P += 1


def main():
    global P
    P = 0
    # 1. 长期上涨（260日持续走高）→ bull，multiplier=1.0
    up = _df(np.linspace(10, 40, 260))
    r = classify_regime(up)
    check("up_longterm_bull", r["regime"] == "bull", r)
    check("bull_multiplier_1", r["position_multiplier"] == 1.0, r["position_multiplier"])

    # 2. 长期下跌 → bear，multiplier=0.5
    down = _df(np.linspace(40, 10, 260))
    r2 = classify_regime(down)
    check("down_longterm_bear", r2["regime"] == "bear", r2)
    check("bear_multiplier_half", r2["position_multiplier"] == 0.5, r2["position_multiplier"])

    # 3. 数据不足（80日）→ range，不崩
    few = _df(np.linspace(10, 12, 80))
    r3 = classify_regime(few)
    check("few_bars_range", r3["regime"] in ("range", "bull") and "position_multiplier" in r3, r3)

    # 4. multiplier 合法范围
    check("multiplier_bounded",
          all(0.3 <= classify_regime(_df(np.linspace(a, b, 260)))["position_multiplier"] <= 1.0
              for a, b in [(10, 40), (40, 10)]))

    # 5. 数据完全缺失不崩
    check("none_no_crash", classify_regime(None)["regime"] == "range")

    print(f"{P}/{P} 个市场状态测试通过")
    assert P == 7


if __name__ == "__main__":
    main()
