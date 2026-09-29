# -*- coding: utf-8 -*-
"""任务书A·模块二：数据质量校验测试。"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("STOCKAI_MOCK", "1")

import numpy as np
import pandas as pd
from core.data_quality import (validate_stock_data, validate_financial_report,
                               validate_report_series, save_quality_report,
                               get_quality_report)

# 1) 构造正常数据 → 通过
idx = pd.date_range("2025-01-01", periods=120, freq="B")
df = pd.DataFrame({
    "open": np.linspace(10, 20, 120), "high": np.linspace(10.5, 20.5, 120),
    "low": np.linspace(9.5, 19.5, 120), "close": np.linspace(10, 20, 120),
    "volume": np.full(120, 1e6),
}, index=idx)
q = validate_stock_data(df)
assert q["passed"] is True, q
assert q["score"] == 100.0, q
print("[ok] 正常数据通过:", q["score"])

# 2) 大量缺失值 + 非正价格 → 不通过
bad = df.copy()
bad.loc[bad.index[5:25], "close"] = np.nan
bad.loc[bad.index[26], "close"] = 0.0
q2 = validate_stock_data(bad)
assert q2["passed"] is False
assert any("缺失值" in i for i in q2["issues"])
assert any("<=0" in i for i in q2["issues"])
assert q2["score"] < 100.0
print("[ok] 缺失/非正价格检出:", q2["score"])

# 3) 极端波动 → 检出（单点扣分，不必然判失败）
jump = df.copy()
jump.loc[jump.index[10], "close"] = df["close"].iloc[10] * 2.0
q3 = validate_stock_data(jump)
assert q3["checks"]["jumps_close"] >= 1, q3
assert q3["score"] < 100.0
print("[ok] 极端波动检出:", q3["checks"]["jumps_close"], "score", q3["score"])

# 4) 时间缺口 → 检出
gap = df.copy()
gap = gap.drop(gap.index[20:30])
q4 = validate_stock_data(gap)
assert q4["checks"]["gap_days"] >= 1
print("[ok] 交易日缺口检出:", q4["checks"]["gap_days"])

# 5) 财报校验
good = {"period": "2026-06-30", "revenue": 100.0, "net_profit": 10.0, "gross_margin": 30.0}
r = validate_financial_report(good)
assert r["passed"] is True and r["score"] == 100.0
bad_r = {"period": "", "revenue": -1.0, "net_profit": None, "gross_margin": 150.0}
r2 = validate_financial_report(bad_r)
assert not r2["passed"]
print("[ok] 财报字段/数值校验")

# 6) 多期一致性（倒挂检出）
series = [{"period": "2026-06-30"}, {"period": "2025-12-31"}, {"period": "2026-03-31"}]
sr = validate_report_series(series)
assert not sr["passed"]
sr2 = validate_report_series([{"period": "2025-12-31"}, {"period": "2026-03-31"}])
assert sr2["passed"]
print("[ok] 多期排序一致性")

# 7) 持久化
save_quality_report("TEST-DQ", {"score": 88.0, "passed": True})
got = get_quality_report("TEST-DQ")
assert got and got["score"] == 88.0 and got["fetched_at"]
print("[ok] 质量报告持久化")

print("\nALL PASS")
