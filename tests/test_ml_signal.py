# -*- coding: utf-8 -*-
"""core.quant.ml_signal 随机森林 ML 信号单测：合成序列，零网络。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd

from core.quant.ml_signal import ml_signal


def _df(prices):
    idx = pd.bdate_range("2024-01-01", periods=len(prices))
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
    np.random.seed(0)
    # 带噪声+周期的趋势序列（有涨有跌，可训练）
    t = np.arange(320)
    price = 10 + 0.02 * t + 0.6 * np.sin(t / 7.0) + np.random.normal(0, 0.25, 320)
    r = ml_signal(_df(price))
    check("ml_runs", r["up_prob"] is not None, r)
    check("prob_bounded", 0.0 <= r["up_prob"] <= 1.0, r["up_prob"])
    check("signal_text", isinstance(r["signal"], str) and "ML" in r["signal"], r["signal"])
    check("top_features_list", isinstance(r["top_features"], list))
    check("n_samples_pos", r["n_samples"] > 100, r["n_samples"])

    # 数据不足 → 优雅降级
    few = ml_signal(_df(np.linspace(10, 12, 40)))
    check("few_bars_degrade", few["up_prob"] is None and "数据不足" in few["signal"], few)

    # None 不崩
    check("none_no_crash", ml_signal(None)["up_prob"] is None)

    # 样本内命中率在合理区间（>0.4 <1.0）
    check("acc_reasonable", 0.4 <= r.get("train_acc_ref", 0) <= 1.0, r.get("train_acc_ref"))

    print(f"{P}/{P} 个 ML 信号测试通过")
    assert P == 8


if __name__ == "__main__":
    main()
