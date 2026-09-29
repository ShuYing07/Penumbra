# -*- coding: utf-8 -*-
"""任务书B·模块三：组合优化扩展（最大分散化 / 分布鲁棒 CVaR）测试。"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("STOCKAI_MOCK", "1")

import numpy as np
import pandas as pd
from core.portfolio_optimizer import optimize_portfolio

# 构造 3 标的、120 日收益（相关性差异）
np.random.seed(7)
n, days = 3, 120
base = np.random.default_rng(42).normal(0.0004, 0.015, (days, n))
ret = pd.DataFrame(base, columns=["A", "B", "C"])

# 1) 最大分散化：ok + 权重归一 + 单只上限
o = optimize_portfolio(ret, method="maxdiv", max_weight=0.5)
assert o["ok"] is True, o
w = o["weights"]
assert abs(sum(w.values()) - 100.0) < 1.0
assert max(w.values()) <= 50.5
assert o["engine"] == "numpy"
print("[ok] 最大分散化:", w)

# 2) 分布鲁棒 CVaR
o2 = optimize_portfolio(ret, method="cvar", max_weight=0.5)
assert o2["ok"] is True
assert abs(sum(o2["weights"].values()) - 100.0) < 1.0
assert max(o2["weights"].values()) <= 50.5
print("[ok] 分布鲁棒 CVaR:", o2["weights"])

# 3) 原方法回归（mv/rp/hrp 仍可用）
for m in ("mv", "rp", "hrp"):
    o3 = optimize_portfolio(ret, method=m)
    assert o3["ok"] is True and abs(sum(o3["weights"].values()) - 100.0) < 1.0
print("[ok] mv/rp/hrp 回归")

# 4) 数据不足保护
small = ret.iloc[:20]
o4 = optimize_portfolio(small, method="maxdiv")
assert o4["ok"] is False and "数据不足" in o4["note"]
print("[ok] 数据不足保护")

print("\nALL PASS")
