# -*- coding: utf-8 -*-
"""相似历史形态检索（StockLLM 思路的确定性实现）。

方法：把"最近 N 个交易日的对数收益向量"与全历史同长度窗口做余弦相似匹配，
返回最相似的 K 段历史行情及其后 M 个交易日的真实表现（涨跌/最大回撤/最大上涨）。

纪律：
- 匹配窗口与其后向窗口在时间上不与当前窗口重叠（后向数据必须已存在），
  因此不存在前视偏差——检索是"现在"做的，用的是当时真实可得的数据；
- 纯 numpy 向量化，6000 根日线毫秒级完成，不落库、不联网。
"""
from __future__ import annotations

import logging

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

log = logging.getLogger("stockai.patterns")

WINDOW = 20     # 形态窗口：近 20 个交易日
FORWARD = 10    # 后向观察：其后 10 个交易日
TOP_K = 5


def find_similar(bars, window: int = WINDOW, forward: int = FORWARD,
                 top_k: int = TOP_K) -> tuple[list[dict], dict | None]:
    """返回 (匹配列表, 聚合摘要)。数据不足返回 ([], None)。"""
    try:
        closes = bars["close"].astype(float).to_numpy()
        dates = bars.index
    except Exception:  # noqa: BLE001
        return [], None
    if len(closes) < window + forward + 10 or (closes <= 0).any():
        return [], None

    rets = np.diff(np.log(closes))                      # 长度 N-1
    wins = sliding_window_view(rets, window)            # wins[j] = rets[j : j+window]
    cur = wins[-1]
    cur_n = cur / (np.linalg.norm(cur) or 1.0)

    # 候选窗口必须满足：其后的 forward 根K线已存在 → j + window + forward <= N-1
    max_j = len(rets) - window - forward
    if max_j < 10:  # 可比历史太短
        return [], None
    cand = wins[: max_j + 1]
    norms = np.linalg.norm(cand, axis=1)
    norms[norms == 0] = 1.0
    sims = (cand @ cur_n) / norms                       # 余弦相似 ∈ [-1, 1]

    order = np.argsort(-sims)[: max(1, top_k)]
    results: list[dict] = []
    for j in order:
        end_i = int(j) + window                         # 收益窗口末根K线在 closes 的下标
        seg = closes[end_i : end_i + forward + 1]
        fwd = float(seg[-1] / seg[0] - 1.0)
        peak = np.maximum.accumulate(seg)
        dd = float((seg / peak - 1.0).min())
        up = float(seg.max() / seg[0] - 1.0)
        results.append({
            "start_date": dates[int(j)].strftime("%Y-%m-%d"),
            "end_date": dates[end_i].strftime("%Y-%m-%d"),
            "similarity_pct": round(float(sims[j]) * 100, 1),
            "forward_ret_pct": round(fwd * 100, 2),
            "forward_dd_pct": round(dd * 100, 2),
            "forward_max_up_pct": round(up * 100, 2),
        })

    fws = [r["forward_ret_pct"] for r in results]
    agg = {"window": window, "forward": forward,
           "avg_forward_ret_pct": round(float(np.mean(fws)), 2),
           "up_ratio_pct": round(sum(1 for x in fws if x > 0) / len(fws) * 100, 1)}
    return results, agg
