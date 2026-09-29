# -*- coding: utf-8 -*-
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("STOCKAI_MOCK", "1")

from context_manager import extract_explicit_refs, build_context_block

# @显式引用
refs = extract_explicit_refs("@茅台 你觉得最近怎么样")
assert refs and "SH600519" in refs, refs
refs2 = extract_explicit_refs("对比 @AAPL 和 @0700.HK")
assert "AAPL" in refs2 and "0700.HK" in refs2, refs2
print("[ok] @显式引用:", refs, refs2)

# 上下文块组装
blk = build_context_block("分析一下",
                          page="K线图", stock="AAPL", skill="technical_analysis",
                          history=[{"role": "user", "content": "刚才看了苹果"}])
assert "当前页面：K线图" in blk and "当前选中股票：AAPL" in blk
assert "分析技能：technical_analysis" in blk and "合规基线" in blk
print("[ok] 上下文块优先级组装")

# AgentCore 注入 context 不崩
from agent.agent_core import AgentCore
c = AgentCore(mock=True)
r = c.run("技术面分析一下 @茅台", context={"page": "K线图", "stock": "SH600519"})
assert r["answer"], r
print("[ok] AgentCore 上下文注入:", r["answer"][:60])

print("\nALL PASS")
