# -*- coding: utf-8 -*-
"""回测分级审计报告（模块四 · 参考 quant-backtest-guard 分级输出）。

把历轮已实现的审计能力（guard_checklist 照妖镜 / nullius 阴性对照 /
audit 前视扫描 + Walk-Forward）打包成统一的**分级体检报告**：

- 致命（critical）：未来函数 / 标签泄漏（前视偏差 fail）
- 高危（high）：过拟合 / 数据窥探（样本外退化）、成交真实性存疑、
  阴性对照不显著（策略收益不优于随机）
- 提示（info）：幸存者偏差（数据覆盖不足）、样本偏短、费用假设说明

输出 {grade, score, items: [{level, name, detail}], summary, passed}。
全部为客观评估，供回测结果页直接展示。
"""
from __future__ import annotations

import logging
import os
import sys
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

import pandas as pd

from core.quant.audit import scan_lookahead, walk_forward
from core.quant.guard_checks import guard_checklist
from core.quant.nullius import negative_control

log = logging.getLogger("stockai.quant.audit_report")


def backtest_audit(df: pd.DataFrame, market: str, strategy: str,
                   params: Optional[dict] = None, config=None,
                   n_perm: int = 200) -> dict:
    """回测分级审计。返回 {grade, score, items, summary, passed}。

    grade: A（全部通过）/ B（有提示）/ C（有高危）/ D（有致命）。
    """
    items: list[dict] = []

    # ---- 致命：未来函数 / 前视偏差 ----
    la = scan_lookahead(df, strategy, params)
    la_passed = bool(la.get("passed"))
    items.append({
        "level": "critical" if not la_passed else "info",
        "name": "未来函数 / 前视偏差（scan_lookahead）",
        "detail": la.get("details", "")[:160] or (
            "信号在截断未来数据后保持一致" if la_passed else "存在可疑偏移"),
    })

    # ---- 高危：过拟合 / 样本外退化 ----
    try:
        wf = walk_forward(df, in_ratio=0.6)
        oos = wf.get("oos") or {}
        is_ = wf.get("in") or {}
        oos_ret = float(oos.get("annual_return", 0.0) or 0.0)
        in_ret = float(is_.get("annual_return", 0.0) or 0.0)
        if in_ret > 0 and oos_ret < 0:
            items.append({"level": "high", "name": "过拟合 / 样本外退化",
                          "detail": f"样本内年化 {in_ret:.1%} 为正，样本外 {oos_ret:.1%} 转负——策略可能过拟合历史"})
        elif oos_ret < in_ret * 0.5:
            items.append({"level": "high", "name": "样本外表现显著退化",
                          "detail": f"样本外年化 {oos_ret:.1%} 显著低于样本内 {in_ret:.1%}"})
        else:
            items.append({"level": "info", "name": "样本外稳健性",
                          "detail": f"样本内 {in_ret:.1%} / 样本外 {oos_ret:.1%} 年化，无显著退化"})
    except Exception as e:  # noqa: BLE001
        items.append({"level": "high", "name": "样本外退化（不可计算）",
                      "detail": f"{e}"})

    # ---- 高危：阴性对照（证伪优先） ----
    try:
        nc = negative_control(df, market, strategy, params, config,
                              n_perm=n_perm)
        if "error" in nc:
            items.append({"level": "high", "name": "阴性对照（证伪优先）",
                          "detail": nc["error"]})
        elif not nc.get("significant", False):
            items.append({"level": "high", "name": "阴性对照不显著",
                          "detail": (f"真实策略收益百分位 {nc.get('percentile', 0):.0f}%"
                                     f"（z={nc.get('z_score', 0):.2f}），未显著优于随机信号"
                                     f"——收益可能来自运气")})
        else:
            items.append({"level": "info", "name": "阴性对照通过",
                          "detail": (f"真实策略显著优于随机信号"
                                     f"（百分位 {nc.get('percentile', 0):.0f}%，"
                                     f"z={nc.get('z_score', 0):.2f}）")})
    except Exception as e:  # noqa: BLE001
        items.append({"level": "high", "name": "阴性对照失败", "detail": str(e)})

    # ---- 提示：幸存者偏差 / 覆盖完整 / 费用 ----
    gc = guard_checklist(df, market, strategy, params, config)
    for c in gc.get("checks", []):
        status, name, detail = c.get("status"), c.get("name"), c.get("detail", "")
        if status == "fail":
            items.append({"level": "critical", "name": name, "detail": detail})
        elif status == "warn":
            items.append({"level": "info", "name": name, "detail": detail})
        else:
            items.append({"level": "info", "name": f"{name}（通过）",
                          "detail": detail})

    # ---- 分级与评分 ----
    critical = sum(1 for i in items if i["level"] == "critical")
    high = sum(1 for i in items if i["level"] == "high")
    base = 100 - critical * 25 - high * 10
    score = max(0, min(100, base))
    grade = "A" if critical == 0 and high == 0 else \
            ("B" if critical == 0 else
             ("C" if high > 0 else "D"))
    passed = critical == 0 and high == 0
    summary = (f"回测体检：{grade} 级（评分 {score}/100），"
               f"致命 {critical} 项 / 高危 {high} 项 / 提示 "
               f"{sum(1 for i in items if i['level'] == 'info')} 项")
    return {"grade": grade, "score": score, "items": items,
            "summary": summary, "passed": passed}


if __name__ == "__main__":
    import numpy as np
    rng = np.random.default_rng(11)
    close = pd.Series(100 * np.cumprod(1 + rng.normal(0.001, 0.02, 300)))
    bars = pd.DataFrame({"open": close, "high": close * 1.01,
                         "low": close * 0.99, "close": close,
                         "volume": rng.integers(1e5, 5e5, 300)},
                        index=pd.date_range("2024-01-01", periods=300))
    r = backtest_audit(bars, "CN", "ma_cross", n_perm=40)
    assert r["grade"] in ("A", "B", "C", "D")
    assert 0 <= r["score"] <= 100
    assert r["summary"] and isinstance(r["items"], list)
    assert any(i["level"] == "info" for i in r["items"])
    print(f"backtest_audit self-check ok ({r['grade']} / {r['score']})")
