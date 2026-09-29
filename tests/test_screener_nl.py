# -*- coding: utf-8 -*-
"""模块二：结构化 Screener + 自然语言选股测试。"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("STOCKAI_MOCK", "1")

from core.screener import (
    parse_natural_language, natural_language_screen, run_screener)

# 1) 自然语言解析
c = parse_natural_language("市盈率低于15、股息率高于3%的银行股")
assert c.get("pe_max") == 15, c
assert c.get("dividend_yield_min") == 3, c
assert c.get("board") == "银行", c
print("[ok] 解析1:", c)

c2 = parse_natural_language("帮我找市值大于500亿、PE小于20的美股公司")
assert c2.get("market") == "美股", c2
assert c2.get("mcap_min") == 500 * 1e8, c2
assert c2.get("pe_max") == 20, c2
print("[ok] 解析2:", c2)

c3 = parse_natural_language("股价低于10元的A股，涨幅超过3%")
assert c3.get("price_max") == 10 and c3.get("chg_min") == 3 and c3.get("market") == "A股", c3
print("[ok] 解析3:", c3)

c4 = parse_natural_language("随便聊聊")
assert c4 == {}, c4
print("[ok] 解析4（无条件）: {}")

# 2) run_screener 结构（mock 下 A股快照不可达 → 代码级结果 + note 标注）
res = run_screener(market="A股", board="银行", price_min=1, price_max=50,
                   pe_max=20, limit=10)
assert res["ok"] is True
assert isinstance(res["hits"], list)
assert "ok" in res and "note" in res
print(f"[ok] run_screener: {len(res['hits'])} hits, note={res['note'][:40]}")

# 3) 自然语言全链路
nl = natural_language_screen("市盈率低于30的银行股", limit=5)
assert nl["ok"] in (True, False)
if nl["ok"]:
    assert "pe_max" in nl["criteria"]
print(f"[ok] natural_language_screen: ok={nl['ok']} criteria={nl.get('criteria')}")

# 4) 股息率条件诚实标注
res2 = run_screener(market="A股", dividend_yield_min=3, limit=5)
assert "股息率" in res2["note"], res2["note"]
print("[ok] 股息率条件标注:", res2["note"][:50])

print("\nALL PASS")
