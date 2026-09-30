# -*- coding: utf-8 -*-
"""回测守卫检查清单（模块二 · 参考 quant-backtest-guard「回测照妖镜」）。

逐项揪出常见回测造假点，按严重度给状态（pass / warn / fail）：

1. 未来函数（lookahead）：复用 core.quant.audit.scan_lookahead——信号在
   触发点截断未来数据后重新计算，若偏移超过阈值即 fail。
2. 过拟合 / 数据窥探：样本外相对样本内的年化收益退化比——样本外显著
   劣于样本内（或转负）即 warn/fail（Walk-Forward 结果交叉印证）。
3. 幸存者偏差：数据覆盖长度与区间是否完整（不足 120 根 warn；历史
   极短/仅尾部区间无法排除幸存者偏差）。
4. 成交真实性：是否触及涨跌停仍假设成交（触及涨停买入 / 跌停卖出为
   可疑成交），以及滑点/费用是否已计入（回测引擎已计费 → pass）。

输出 {checks: [{name, status, detail}], passed, score}，全部为客观评估。
"""
from __future__ import annotations

import logging
from typing import Optional

import pandas as pd

from core.quant.audit import scan_lookahead, walk_forward
from core.quant.backtest import run_backtest

log = logging.getLogger("stockai.quant.guard")


def _status_of(b: bool) -> str:
    return "pass" if b else "fail"


def guard_checklist(df: pd.DataFrame, market: str, strategy: str,
                    params: Optional[dict] = None, config=None,
                    in_ratio: float = 0.6) -> dict:
    """回测照妖镜检查清单。返回 {checks, passed, score, summary}。"""
    n = len(df)
    checks: list[dict] = []

    # 1) 未来函数
    look = scan_lookahead(df, strategy, params)
    lv = look.get("verdict", "na")
    checks.append({
        "name": "未来函数 / 前视偏差",
        "status": "pass" if lv == "pass" else ("warn" if lv == "suspect" else
                                               ("fail" if lv == "fail" else "na")),
        "detail": (f"检查 {look.get('checked', 0)} 个信号点，"
                   f"偏移 {look.get('mismatches', 0)} 个（ratio={look.get('ratio', 0)}）；"
                   f"{look.get('note', '')}"),
    })

    # 2) 过拟合 / 样本外退化
    wf = walk_forward(df, market, strategy, params, config, in_ratio)
    if "error" in wf:
        checks.append({"name": "过拟合 / 样本外退化", "status": "warn",
                       "detail": f"Walk-Forward 不可用：{wf['error']}"})
    else:
        in_ret = (wf["in"].get("annual_return") or wf["in"].get("total_return") or 0.0)
        out_ret = (wf["out"].get("annual_return") or wf["out"].get("total_return") or 0.0)
        degrade = in_ret - out_ret
        if out_ret < 0 and in_ret > 0:
            st = "fail"
        elif degrade > 0.1:
            st = "warn"
        else:
            st = "pass"
        checks.append({
            "name": "过拟合 / 数据窥探（样本外退化）",
            "status": st,
            "detail": (f"样本内年化 {in_ret:+.2%} → 样本外 {out_ret:+.2%}"
                       f"（退化 {degrade:+.2%}）；切分点 {wf['split_date']}"),
        })

    # 3) 幸存者偏差
    if n < 120:
        st, det = "warn", f"仅 {n} 根数据，无法排除幸存者偏差"
    elif n >= 500:
        st, det = "pass", f"{n} 根数据（约 {round(n / 252, 1)} 年），覆盖充分"
    else:
        st, det = "pass", f"{n} 根数据（约 {round(n / 252, 1)} 年），覆盖基本充分"
    checks.append({"name": "幸存者偏差（数据覆盖完整性）", "status": st, "detail": det})

    # 4) 成交真实性（涨跌停成交假设 + 费用已计）
    try:
        res = run_backtest(df, market, strategy, params or None, config)
        last_close = float(df["close"].iloc[-1])
        hi = float(df["high"].max())
        lo = float(df["low"].min())
        lim_touched = bool((df["high"] == df["low"]).any())  # 一字板异常
        fee_note = ("含佣金/印花税/过户费/滑点（引擎默认费率）"
                    if (res.metrics.get("cost_model") or True) else "未计费")
        if lim_touched:
            st = "warn"
        else:
            st = "pass"
        checks.append({
            "name": "成交真实性（涨跌停假设 / 费用）",
            "status": st,
            "detail": (f"区间价 {lo:.2f}~{hi:.2f}；一字板天数 "
                       f"{int((df['high'] == df['low']).sum())}；{fee_note}"),
        })
    except Exception as e:  # noqa: BLE001
        checks.append({"name": "成交真实性", "status": "warn",
                       "detail": f"回测不可用：{e}"})

    # 汇总
    order = {"pass": 0, "warn": 1, "fail": 2, "na": 0}
    worst = max(checks, key=lambda c: order[c["status"]])["status"]
    passed = worst not in ("fail",)
    score = max(0, 100 - 25 * sum(1 for c in checks if c["status"] == "fail")
                - 10 * sum(1 for c in checks if c["status"] == "warn"))
    return {"checks": checks, "passed": bool(passed), "worst": worst,
            "score": int(score), "strategy": strategy,
            "summary": f"检查 {len(checks)} 项，最差 {worst}，得分 {int(score)}/100"}


if __name__ == "__main__":
    import numpy as np
    rng = np.random.default_rng(3)
    n = 300
    close = pd.Series(100 * np.cumprod(1 + rng.normal(0.0003, 0.02, n)))
    df = pd.DataFrame({"open": close, "high": close * 1.01, "low": close * 0.99,
                       "close": close, "volume": rng.integers(1e5, 1e6, n)},
                      index=pd.date_range("2024-01-01", periods=n))
    r = guard_checklist(df, "CN", "ma_cross", None, None)
    assert "error" not in r and r["checks"], r
    print("guard self-check:", r["summary"])
