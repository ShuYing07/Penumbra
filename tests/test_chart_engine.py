# -*- coding: utf-8 -*-
"""第17轮·模块四：可视化引擎核心测试（指标库 / 绘图工具 / AI 控制面）。

注：环境无 QtWebEngine，故以可测的原生内核为核心交付物：
- 90+ 命名指标配置；42+ 绘图工具；MCP 兼容 apply_chart_command 控制面。
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("STOCKAI_MOCK", "1")

from core.chart_engine import (ChartState, apply_chart_command, compute_chart_payload,
                              compute_indicator, list_drawing_tools, list_indicators)

# 1) 指标库 ≥ 90（对标 Vela / fast-financial-charts 丰富度）
inds = list_indicators()
assert len(inds) >= 90, f"指标不足 90：{len(inds)}"
for it in inds:
    assert it["id"] and it["name"] and it["panel"] in ("price", "sub")
print(f"[ok] 指标库 {len(inds)} 个（≥90），覆盖类别："
      + "、".join(sorted({i['category'] for i in inds})))

# 2) 绘图工具 ≥ 42
tools = list_drawing_tools()
assert len(tools) >= 42, f"绘图工具不足 42：{len(tools)}"
ids = {t["id"] for t in tools}
for need in ("trend_line", "fib_retracement", "parallel_channel", "head_shoulders_zone",
             "stop_loss_line", "volume_profile_bar", "regression_channel"):
    assert need in ids, need
print(f"[ok] 绘图工具 {len(tools)} 个（≥42），含趋势/斐波/通道/形态/风控类")

# 3) 每个指标都能在 OHLCV 上计算且不报错、长度一致
idx = pd.bdate_range("2024-01-01", periods=150)
rng = np.random.default_rng(3)
close = 10 * np.exp(np.linspace(0, 0.3, 150) + rng.normal(0, 0.01, 150).cumsum())
df = pd.DataFrame({"open": close, "high": close * 1.01, "low": close * 0.99,
                  "close": close, "volume": rng.integers(1_000, 5_000, 150).astype(float)},
                 index=idx)
fail = []
for it in inds:
    try:
        ser = compute_indicator(it["id"], df)
        if len(ser) != len(df):
            fail.append(it["id"] + f"(len={len(ser)})")
    except Exception as e:  # noqa: BLE001
        fail.append(it["id"] + f"({type(e).__name__})")
assert not fail, f"以下指标计算异常：{fail[:10]}"
print(f"[ok] 全部 {len(inds)} 个指标在 150 根 OHLCV 上计算通过")

# 4) AI 控制面：增删指标 / 绘图 / 周期 / 校验 / 重置
st = ChartState(ticker="SH600519")
r = apply_chart_command(st, {"action": "set_ticker", "ticker": "SH600519"})
assert r["ok"]
r = apply_chart_command(st, {"action": "add_indicator", "id": "MA20"})
assert r["ok"] and len(st.indicators) == 1
r = apply_chart_command(st, {"action": "add_indicator", "id": "MA20"})  # 去重
assert r["ok"] and len(st.indicators) == 1
r = apply_chart_command(st, {"action": "add_indicator", "id": "EMA12"})
assert len(st.indicators) == 2
r = apply_chart_command(st, {"action": "set_timeframe", "tf": "1w"})
assert r["ok"] and st.timeframe == "1w"
r = apply_chart_command(st, {"action": "set_timeframe", "tf": "bad"})
assert not r["ok"]   # 非法周期被拒
r = apply_chart_command(st, {"action": "add_drawing", "tool": "fib_retracement",
                            "points": [{"x": 10, "y": 100}, {"x": 30, "y": 80}]})
assert r["ok"] and len(st.drawings) == 1
r = apply_chart_command(st, {"action": "add_indicator", "id": "NOPE"})
assert not r["ok"]   # 未知指标被拒
r = apply_chart_command(st, {"action": "remove_indicator", "id": "MA20"})
assert r["ok"] and len(st.indicators) == 1
r = apply_chart_command(st, {"action": "remove_last_drawing"})
assert r["ok"] and len(st.drawings) == 0
r = apply_chart_command(st, {"action": "reset"})
assert r["ok"] and len(st.indicators) == 0 and len(st.drawings) == 0
print("[ok] AI 控制面：ticker/tf/增删指标/绘图/校验/重置 全部正确")

# 5) 计算图表负载（price/sub 分组 + 绘图）
apply_chart_command(st, {"action": "add_indicator", "id": "MA20"})
apply_chart_command(st, {"action": "add_indicator", "id": "RSI14"})
apply_chart_command(st, {"action": "add_drawing", "tool": "trend_line",
                        "points": [{"x": 0, "y": 10}]})
payload = compute_chart_payload(st, df)
assert len(payload["price_indicators"]) == 1
assert payload["price_indicators"][0]["id"] == "MA20"
assert len(payload["sub_indicators"]) == 1
assert payload["sub_indicators"][0]["id"] == "RSI14"
assert len(payload["drawings"]) == 1
assert payload["timeframe"] == "1d"
print("[ok] compute_chart_payload 按 panel 分组输出 price/sub + drawings")

print("\nALL PASS")
