# -*- coding: utf-8 -*-
"""任务书B·模块一：多智能体投研团队（并行执行组 + 组合经理）测试。"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("STOCKAI_MOCK", "1")

from core.agents.analyst_team import (ANALYST_DEFS, macro_analyst,
                                      deep_researcher, run_data_group,
                                      run_synthesis_group, InvestmentManager,
                                      run_analysis_team, save_analysis_context)

# 1) 分析师注册表：7 名，两组
assert len(ANALYST_DEFS) == 7
data_group = [a["key"] for a in ANALYST_DEFS if a["group"] == "data"]
synth_group = [a["key"] for a in ANALYST_DEFS if a["group"] == "synthesis"]
assert set(data_group) == {"technical", "fundamental", "news", "sentiment"}
assert set(synth_group) == {"macro", "risk_assessor", "deep_researcher"}
print("[ok] 7 分析师注册:", data_group, "/", synth_group)

# 2) 宏观分析师（确定性，regime 缺失降级）
m1 = macro_analyst({})
assert m1["stance"] == "中性" and m1["confidence"] < 0.5
m2 = macro_analyst({"regime": {"market": "上涨", "trend": "牛市", "volatility": "低"}})
assert m2["stance"] == "看多"
print("[ok] 宏观分析师规则:", m1["stance"], "→", m2["stance"])

# 3) 深度研究员（跨维度综合 + 分歧检测）
st = {"signals": {"technical": {"stance": "看多", "confidence": 0.8},
                  "fundamental": {"stance": "看多", "confidence": 0.7},
                  "news": {"stance": "看空", "confidence": 0.6},
                  "sentiment": {"stance": "看空", "confidence": 0.6}}}
d1 = deep_researcher(st)
assert d1["stance"] in ("看多", "中性", "看空")
assert d1["score"] is not None
print("[ok] 深度研究综合分:", d1["score"], d1["stance"])

# 4) 数据组并行执行（mock runner）
class _MockRunner:
    mock = True

    def chat_json(self, node, system, user):
        return None  # 触发节点降级 → 仍返回信号结构

r = _MockRunner()
state = {"ticker": "SH600519", "name": "贵州茅台", "market": "CN",
         "quote": {"price": 100.0, "prev_close": 99.0, "chg_pct": 1.0},
         "signals": {}, "tech": {"close": 100.0},
         "news": [], "funda": {}}
state2 = run_data_group(state, r)
for k in ("technical", "fundamental", "news", "sentiment"):
    assert k in state2["signals"], k
print("[ok] 数据组并行:", sorted(state2["signals"]))

# 5) 综合组并行
state3 = run_synthesis_group(state2, r)
for k in ("macro", "risk_assess", "deep_research"):
    assert k in state3["signals"], k
print("[ok] 综合组并行:", sorted(state3["signals"]))

# 6) 投资组合经理（风控否决 / 批准）
im = InvestmentManager()
rej = im.review({"signals": {"risk_assess": {"risk_level": "高", "var95_pct": 3.0}},
                 "final": {"leader": {"consensus": "强烈看多"}}})
assert rej["decision"] == "rejected" and "否决" in rej["summary"]
appr = im.review({"signals": {"risk_assess": {"risk_level": "低", "var95_pct": 2.0,
                                              "vol_annual_pct": 20.0}},
                  "final": {"leader": {"consensus": "看多"}}})
assert appr["decision"] == "approved" and appr["max_position"] > 0
print("[ok] 组合经理:", rej["decision"], "/", appr["decision"])

# 7) 全流程（mock 环境）
full = run_analysis_team("SH600519", runner=r)
assert "signals" in full and "investment" in full
assert full["investment"]["decision"] in ("approved", "rejected", "conditional")
assert full.get("context_file")
print("[ok] 全流程:", full["investment"]["decision"], "→", full["context_file"])

print("\nALL PASS")
