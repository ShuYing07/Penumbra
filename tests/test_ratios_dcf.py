# -*- coding: utf-8 -*-
"""任务书B·模块四：财务比率 + DCF 模型测试。"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("STOCKAI_MOCK", "1")

from core.financial_report_parser import calculate_ratios, render_ratios_card, \
    build_dcf_model, render_dcf_card

# 1) 比率计算：字段齐全
report = {"revenue": 100.0, "net_profit": 10.0, "gross_margin": 30.0,
          "total_assets": 200.0, "total_liabilities": 80.0, "equity": 120.0,
          "operating_cashflow": 12.0, "inventory": 20.0, "accounts_receivable": 15.0,
          "revenue_yoy": 12.0, "profit_yoy": 15.0, "roe": 8.3, "pe": 25.0,
          "pb": 3.0, "market_cap": 250.0}
out = calculate_ratios(report)
assert out["ok"] is True, out
r = out["ratios"]
assert r["net_margin_pct"] == 10.0          # 10/100*100
assert r["debt_to_assets_pct"] == 40.0      # 80/200*100
assert r["assets_to_equity"] == round(200.0 / 120.0, 2)
assert r["pe_implied"] == 250.0 / 10.0
assert "net_margin_pct" in r and "inventory_turnover" in r
print("[ok] 比率计算:", len(r), "项")

# 2) 字段不足 → ok=False 且 missing 标注
out2 = calculate_ratios({"revenue": 1.0})
assert out2["ok"] is False and "数据不足" in out2["note"]
print("[ok] 字段不足降级标注")

# 3) 卡片渲染
html = render_ratios_card(out)
assert "<table" in html and "财务比率" in html
print("[ok] 比率卡片")

# 4) DCF 基准：默认假设可算，三情景单调
dcf = build_dcf_model()
assert dcf["ok"]
sc = dcf["scenarios"]
assert sc["pessimistic"] < sc["base"] < sc["optimistic"]
assert len(dcf["sensitivity"]) == 9
assert "不构成投资建议" in dcf["note"]
print("[ok] DCF 三情景:", sc)

# 5) DCF 自定义假设
dcf2 = build_dcf_model({"fcf": 10.0, "growth_rate": 8.0, "discount_rate": 12.0,
                        "terminal_growth": 3.0})
assert dcf2["ok"] and dcf2["assumptions"]["fcf0"] == 10.0
assert dcf2["scenarios"]["base"] > 0
print("[ok] DCF 自定义假设:", dcf2["scenarios"]["base"])

# 6) DCF 卡片
h2 = render_dcf_card(dcf2)
assert "DCF" in h2 and "情景" in h2
print("[ok] DCF 卡片")

print("\nALL PASS")
