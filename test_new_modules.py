# -*- coding: utf-8 -*-
"""测试新模块"""
import sys
sys.path.insert(0, '.')

print("=== 1. rigor.py 统计严谨性 ===")
from rigor import test_claim, permutation_test, check_sample_size, correct_multiple_testing
import numpy as np
np.random.seed(42)
a = np.random.normal(0.02, 0.01, 50)
b = np.random.normal(0.00, 0.01, 50)
r = test_claim(a.tolist(), b.tolist(), n_permutations=2000)
print(f"  verdict: {r['verdict']}")
print(f"  p_value: {r['p_value']}")
print(f"  mean_diff: {r['mean_diff']:.4f}")

print("\n=== 2. wyckoff_analyzer.py 威科夫 ===")
from wyckoff_analyzer import analyze_wyckoff
import pandas as pd
dates = pd.date_range("2026-01-01", periods=60)
close = np.cumsum(np.random.randn(60) * 0.5) + 100
df = pd.DataFrame({
    "open": close + np.random.randn(60) * 0.2,
    "high": close + np.abs(np.random.randn(60)) * 0.5,
    "low": close - np.abs(np.random.randn(60)) * 0.5,
    "close": close,
    "volume": np.random.randint(1000000, 5000000, 60),
}, index=dates)
patterns = analyze_wyckoff(df)
print(f"  检测到 {len(patterns)} 个结构")

print("\n=== 3. risk_control_agent.py 风控 ===")
from risk_control_agent import risk_review
test = {
    "bull_case": ["护城河深", "现金流稳定", "分红提升"],
    "bear_case": ["宏观下行"],
    "confidence": 85,
}
rc = risk_review(test)
print(f"  verdict: {rc['verdict']}")
print(f"  warnings: {rc['warnings']}")
print(f"  adjusted_confidence: {rc['adjusted_confidence']}")

print("\n全部通过 ✅")
