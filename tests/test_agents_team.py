# -*- coding: utf-8 -*-
"""模块十：多智能体投研团队（风险评估师 + 首席分析师 Leader）测试。"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("STOCKAI_MOCK", "1")

import numpy as np
import pandas as pd

from core.agents.risk_assessor import assess_risk
from core.agents.graph import run_analysis, NODE_LABELS

# 1) 风险评估师：构造确定性日线序列
n = 120
rng = np.random.default_rng(7)
close = 100 * np.cumprod(1 + rng.normal(0.001, 0.02, n))
df = pd.DataFrame({"close": close}, index=pd.date_range("2025-01-01", periods=n))
r = assess_risk(df)
assert "risk_level" in r and r["risk_level"] in ("低", "中", "高")
assert r["vol_annual_pct"] is not None and r["vol_annual_pct"] > 0
assert r["var95_pct"] is not None and r["var95_pct"] >= 0
assert r["max_drawdown_pct"] is not None and r["max_drawdown_pct"] <= 0
assert "shock_minus_10pct" in r["stress"] and "shock_minus_20pct" in r["stress"]
print(f"[ok] 风险评估师统计量 vol={r['vol_annual_pct']}% var95={r['var95_pct']}% "
      f"mdd={r['max_drawdown_pct']}% level={r['risk_level']}")

# 2) 数据不足降级
r2 = assess_risk(pd.DataFrame({"close": [1.0, 2.0]}))
assert r2["risk_level"] == "数据不足"
print("[ok] 风险评估师数据不足降级")

# 3) 全链路：mock 环境跑完整管线（含 risk_assessor + leader 节点）
res = run_analysis("SH600519", progress_cb=lambda k, p: None, persist=False, light=True)
state = res["state"]
assert "risk_assess" in state and state["risk_assess"].get("risk_level") in ("低", "中", "高", "不可用", "数据不足")
assert isinstance(state.get("final") or {}, dict)
leader = (state.get("final") or {}).get("leader")
assert leader is not None, "final.leader 缺失（首席分析师节点未生效）"
# leader 降级路径也应包含 consensus/final_view
assert "consensus" in leader and "final_view" in leader
# 节点时序（progress_cb 非 None 时收集）
timing = state.get("node_timing") or {}
assert "risk_assessor" in timing and "leader" in timing, f"节点时序缺失：{list(timing.keys())}"
assert NODE_LABELS["risk_assessor"] == "风险评估师"
assert NODE_LABELS["leader"] == "首席分析师"
print(f"[ok] 全链路节点：{list(timing.keys())}")
print(f"[ok] 风险评估={state['risk_assess'].get('risk_level')}；"
      f"leader降级={'降级' in leader['consensus']}")

# 4) 降级扫描：leader 降级应被 degraded_nodes 捕获
from core.agents.graph import degraded_nodes
bad = degraded_nodes(state)
print(f"[ok] 降级节点扫描：{bad}")

print("\nALL PASS")
