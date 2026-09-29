# -*- coding: utf-8 -*-
"""模块四：组合优化测试。"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("STOCKAI_MOCK", "1")

import numpy as np
import pandas as pd

from core.portfolio_optimizer import (
    optimize_portfolio, backtest_portfolio, _np_risk_parity,
    _np_mean_variance, _np_hrp)

rng = np.random.default_rng(7)
idx = pd.date_range("2024-01-01", periods=300, freq="B")
X = pd.DataFrame({
    "SH600519": rng.normal(0.0006, 0.012, 300),
    "SZ300750": rng.normal(0.0003, 0.02, 300),
    "AAPL": rng.normal(0.0004, 0.015, 300),
}, index=idx)

# 1) 三种方法结构
for m, name in (("mv", "均值-方差"), ("rp", "风险平价"), ("hrp", "HRP")):
    r = optimize_portfolio(X, method=m)
    assert r["ok"], r
    assert abs(sum(r["weights"].values()) - 100.0) < 1.5, (name, r["weights"])
    assert r["engine"] in ("numpy", "skfolio")
    assert all(w <= 40.1 for w in r["weights"].values()), (name, r["weights"])  # 单只上限
    assert r["expected_return"] is not None and r["volatility"] > 0
    assert len(r["risk_contrib"]) == 3
    print(f"[ok] {name}: sharpe={r['sharpe']} 权重={r['weights']}")

# 2) 数据不足防护
bad = optimize_portfolio(pd.DataFrame({"A": [1.0]}), method="mv")
assert bad["ok"] is False and "数据不足" in bad["note"]
print("[ok] 数据不足防护")

# 3) 未知方法
unk = optimize_portfolio(X, method="xxx")
assert unk["ok"] is False and "未知方法" in unk["note"]
print("[ok] 未知方法防护")

# 4) 组合回测
prices = (1 + X).cumprod()
r = backtest_portfolio(prices, {"SH600519": 50.0, "SZ300750": 30.0, "AAPL": 20.0})
assert r["ok"], r
assert r["total_return_pct"] is not None and r["bars"] == 300
assert "nav" in r and len(r["nav"]) == 300
print(f"[ok] 组合回测: 总收益 {r['total_return_pct']}% 回撤 {r['max_drawdown_pct']}% 夏普 {r['sharpe']}")

# 5) 内置算法自检（确定性输入 → 权重和≈1）
W = _np_mean_variance(X.values, 0.4, 0.02)
assert abs(W.sum() - 1) < 1e-6 and (W <= 0.4 + 1e-9).all()
W2 = _np_risk_parity(X.values, 0.4)
assert abs(W2.sum() - 1) < 1e-6
W3 = _np_hrp(X.values, 0.4)
assert abs(W3.sum() - 1) < 1e-6 and (W3 >= 0).all()
print("[ok] 内置算法自检")

print("\nALL PASS")
