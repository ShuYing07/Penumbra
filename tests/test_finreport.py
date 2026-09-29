# -*- coding: utf-8 -*-
"""模块三：财报与公告深度解析测试。"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("STOCKAI_MOCK", "1")

from core.financial_report_parser import (
    extract_key_info, render_report_card, render_period_compare,
    get_financial_reports, _rule_extract)

# 1) 规则提取（离线兜底）
info = extract_key_info(
    "公司2026年半年度净利润同比增长15%，签订重大销售合同3亿元，"
    "管理层讨论称海外业务拓展顺利。风险提示：行业竞争加剧。")
assert isinstance(info, dict)
assert "performance" in info and "contracts" in info and "risks" in info
assert info["source"] in ("llm", "rule")
if info["source"] == "rule":
    assert any("净利润" in c for c in [info["performance"]]) or "同比增长" in info["performance"]
print("[ok] extract_key_info source=", info["source"])

# 2) 规则引擎细节
r = _rule_extract("净利润3.5亿元，同比增长20%；中标5G基站项目合同1.2亿元；风险提示：政策变化")
assert r["contracts"] and "合同" in r["contracts"][0], r
assert r["risks"] and "风险提示" in r["risks"][0], r
print("[ok] 规则提取:", r["performance"][:30], "/", len(r["contracts"]), "合同 /", len(r["risks"]), "风险")

# 3) 空文本
e = extract_key_info("")
assert e["performance"] == "无文本可解析", e
print("[ok] 空文本防护")

# 4) 财报获取降级（离线环境必然降级，验证结构不崩）
res = get_financial_reports("SH600519", periods=2)
assert res["ok"] in (True, False)
assert isinstance(res["reports"], list) and isinstance(res["announcements"], list)
assert "note" in res
print("[ok] get_financial_reports:", "reports", len(res["reports"]),
      "announcements", len(res["announcements"]), "note", res["note"][:50])

# 5) 卡片渲染
card = render_report_card("SH600519", info, {"pe_ttm": "22.5", "pb": "8.1",
                                              "total_market_cap": "2.1万亿",
                                              "industry": "白酒"})
assert "估值指标" in card and "业绩变动" in card and "风险提示" in card
print("[ok] render_report_card len=", len(card))

# 6) 多期对比
cmp_html = render_period_compare([])
assert "暂无多期财报数据" in cmp_html
cmp2 = render_period_compare([
    {"period": "2026H1", "revenue": "100亿", "net_profit": "30亿", "gross_margin": "45%"},
    {"period": "2025H1", "revenue": "80亿", "net_profit": "25亿", "gross_margin": "43%"},
])
assert "2026H1" in cmp2 and "2025H1" in cmp2
print("[ok] render_period_compare")

print("\nALL PASS")
