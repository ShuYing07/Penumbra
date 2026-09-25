# -*- coding: utf-8 -*-
"""统计严谨性层：置换检验、样本量门控、多重检验校正。

纯Python实现，不依赖scipy。参考TokIO AI的"拒绝在数据不足时下结论"理念。
"""
from __future__ import annotations

import logging
import random
from typing import Sequence

import numpy as np

log = logging.getLogger("stockai.rigor")

MIN_SAMPLE = 30  # 最小样本量硬性下限


def permutation_test(sample_a: Sequence[float], sample_b: Sequence[float],
                     n_permutations: int = 5000) -> dict:
    """双侧置换检验：检验两组样本均值差异是否显著。

    返回: {observed_diff, p_value, n_permutations, significant}
    """
    a = np.array(sample_a, dtype=float)
    b = np.array(sample_b, dtype=float)
    if len(a) < MIN_SAMPLE or len(b) < MIN_SAMPLE:
        return {
            "observed_diff": float(np.mean(a) - np.mean(b)) if len(a) and len(b) else 0.0,
            "p_value": 1.0,
            "n_permutations": 0,
            "significant": False,
            "warning": f"样本量不足（a={len(a)}, b={len(b)}, 需>={MIN_SAMPLE}）",
        }

    observed = float(np.mean(a) - np.mean(b))
    combined = np.concatenate([a, b])
    n_a = len(a)
    count_extreme = 0

    rng = np.random.default_rng(42)
    for _ in range(n_permutations):
        rng.shuffle(combined)
        perm_diff = float(np.mean(combined[:n_a]) - np.mean(combined[n_a:]))
        if abs(perm_diff) >= abs(observed):
            count_extreme += 1

    p_value = (count_extreme + 1) / (n_permutations + 1)
    return {
        "observed_diff": observed,
        "p_value": round(p_value, 4),
        "n_permutations": n_permutations,
        "significant": p_value < 0.05,
        "warning": None,
    }


def check_sample_size(sample: Sequence, min_size: int = MIN_SAMPLE) -> dict:
    """检查样本量是否足够。"""
    n = len(sample)
    return {
        "n": n,
        "min_required": min_size,
        "adequate": n >= min_size,
        "message": f"样本量 {n}（需>={min_size}）" + ("，充足" if n >= min_size else "，不足"),
    }


def correct_multiple_testing(p_values: Sequence[float], method: str = "bonferroni") -> list[float]:
    """多重检验校正。

    bonferroni: p * n（最简单最保守）
    benjamini: BH-FDR校正
    """
    pvals = np.array(p_values, dtype=float)
    n = len(pvals)
    if n == 0:
        return []

    if method == "bonferroni":
        corrected = np.minimum(pvals * n, 1.0)
        return [float(x) for x in corrected]

    # Benjamini-Hochberg
    order = np.argsort(pvals)
    corrected = np.zeros(n)
    prev = 1.0
    for i in range(n - 1, -1, -1):
        idx = order[i]
        rank = i + 1
        val = min(prev, pvals[idx] * n / rank)
        corrected[idx] = val
        prev = val
    return [float(x) for x in corrected]


def test_claim(condition_data: Sequence[float], outcome_data: Sequence[float],
               n_permutations: int = 5000) -> dict:
    """综合统计检验：检查一个claim是否成立。

    condition_data: 满足条件后的收益序列
    outcome_data: 不满足条件的收益序列（基准）
    """
    size_check = check_sample_size(condition_data)
    perm = permutation_test(condition_data, outcome_data, n_permutations)

    return {
        "sample_size": size_check,
        "permutation": perm,
        "verdict": (
            "统计显著" if perm.get("significant") and size_check["adequate"]
            else "数据不足以支持该结论"
        ),
        "mean_diff": perm.get("observed_diff", 0),
        "p_value": perm.get("p_value", 1.0),
    }


if __name__ == "__main__":
    # 简单自测
    np.random.seed(42)
    a = np.random.normal(0.02, 0.01, 50)   # 条件满足组：均值2%
    b = np.random.normal(0.00, 0.01, 50)   # 基准组：均值0%
    result = test_claim(a.tolist(), b.tolist(), n_permutations=2000)
    print("统计检验结果:")
    for k, v in result.items():
        print(f"  {k}: {v}")
