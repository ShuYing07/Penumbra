# -*- coding: utf-8 -*-
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from skill_loader import list_skills, match_skill, skills_prompt

cats = list_skills()
assert len(cats) == 5, cats
print("[ok] 技能目录:", [c["slug"] for c in cats])

assert match_skill("帮我看看茅台的技术面") == "technical_analysis"
assert match_skill("贵州茅台和腾讯控股对比一下") == "multi_stock_compare"
assert match_skill("这只股票有什么风险") == "risk_assessment"
assert match_skill("多空辩论一下 600519") == "debate_analysis"
assert match_skill("今天天气怎么样") == ""  # 未命中
print("[ok] 触发词匹配")

p = skills_prompt("技术面分析一下茅台")
assert "技术面分析" in p and "当前激活技能" in p
assert skills_prompt("随便聊聊") == ""
print("[ok] 按需注入")

# AgentCore 集成：LLM 合成路径注入技能（mock 环境走模板，验证不崩）
from agent import AgentCore
c = AgentCore(mock=True)
r = c.run("茅台的技术面怎么样")
print("[ok] AgentCore 技能集成:", r["answer"][:40])
print("\nALL PASS")
