# -*- coding: utf-8 -*-
"""第17轮·模块二：PIT-Guard 全数据源覆盖测试。

参考 TradingAgents v0.5.0「point-in-time integrity across every dated path」：
点时间约束必须覆盖每一条带日期的数据路径，而不只是 K 线。
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("STOCKAI_MOCK", "1")

from core.pit_sources import (SOURCE_DATE_FIELDS, pick_date_field, guard_source,
                              guard_all, sources_catalog, _norm_date,
                              _FORBIDDEN_FIELDS)

AS_OF = "2024-03-01"

# 1) 行情：按交易日截断
quotes = [{"date": "2024-02-28", "close": 1.0},
          {"date": "2024-03-05", "close": 2.0}]
r = guard_source("quote", quotes, AS_OF)
assert r["allowed"] and r["kept"] == 1 and r["filtered"] == 1
assert r["field"] == "date"
assert r["data"][0]["close"] == 1.0
print("[ok] quote 按交易日截断 kept=%d filtered=%d" % (r["kept"], r["filtered"]))

# 2) 财报：必须用公告日 ann_date，绝不能用 period_end
fins = [{"ann_date": "2024-02-20", "period_end": "2023-12-31", "rev": 100},
        {"ann_date": "2024-04-10", "period_end": "2023-12-31", "rev": 120}]
r2 = guard_source("financial", fins, AS_OF)
assert r2["allowed"] and r2["kept"] == 1 and r2["filtered"] == 1
assert r2["field"] == "ann_date", r2["field"]
assert r2["data"][0]["rev"] == 100
# 报告期字段在禁用名单内
assert "period_end" in _FORBIDDEN_FIELDS
assert pick_date_field(fins, "financial") == "ann_date"
print("[ok] financial 用公告日=%s 而非 period_end" % r2["field"])

# 3) 财报只有报告期字段 → 严格源阻断（防 30~90 天前视）
bad = [{"period_end": "2023-12-31", "rev": 100}]
r3 = guard_source("financial", bad, AS_OF)
assert r3["allowed"] is False, r3
assert r3["data"] == []
assert "阻断" in r3["reason"]
# filing 同样是严格源
r3b = guard_source("filing", [{"period_end": "2023-06-30", "title": "半年报"}], AS_OF)
assert r3b["allowed"] is False
print("[ok] 严格源缺公告字段阻断：financial/filing")

# 4) 非严格源缺字段 → 放行但标注 untested
r4 = guard_source("news", [{"title": "无日期新闻"}], AS_OF)
assert r4["allowed"] and "untested" in r4["reason"]
assert r4["kept"] == 1
r4b = guard_source("social", [{"text": "无时间戳情绪"}], AS_OF)
assert r4b["allowed"] and "untested" in r4b["reason"]
print("[ok] 非严格源缺字段放行+标注 untested")

# 5) 宏观（FRED）/ 社交 / 决策日志 均被覆盖
macro = [{"date": "2024-01-15", "v": 3.2}, {"date": "2024-05-01", "v": 3.9}]
r5 = guard_source("macro", macro, AS_OF)
assert r5["allowed"] and r5["kept"] == 1 and r5["filtered"] == 1
social = [{"ts": "2024-02-01 10:00:00", "s": 0.3}, {"ts": "2024-03-09 10:00:00", "s": 0.8}]
r6 = guard_source("social", social, AS_OF)
assert r6["allowed"] and r6["kept"] == 1 and r6["filtered"] == 1
assert r6["field"] == "ts"
log = [{"ts": "2024-02-10", "act": "buy"}, {"ts": "2024-03-20", "act": "sell"}]
r7 = guard_source("decision_log", log, AS_OF)
assert r7["allowed"] and r7["kept"] == 1 and r7["filtered"] == 1
for src in ("quote", "bars", "news", "filing", "financial", "macro",
            "social", "decision_log"):
    assert src in SOURCE_DATE_FIELDS, src
print("[ok] 8 个数据源全部覆盖（含 FRED宏观/社交情绪/决策日志）")

# 6) 多源一次性守卫
allr = guard_all({"quote": quotes, "financial": fins,
                  "social": social, "macro": macro}, AS_OF)
assert allr["total_filtered"] == 4, allr
assert allr["blocked"] == []
assert isinstance(allr["results"], dict) and len(allr["results"]) == 4
assert "守卫" in allr["summary"]
# 含严格源阻断时，blocked 记录源名
allr2 = guard_all({"financial": bad, "quote": quotes}, AS_OF)
assert "financial" in allr2["blocked"], allr2["blocked"]
print("[ok] guard_all：blocked=%s total_filtered=%d" %
      (allr2["blocked"], allr["total_filtered"]))

# 7) 日期归一化：多种格式
assert _norm_date("2024-01-05") == "20240105"
assert _norm_date("20240105") == "20240105"
assert _norm_date("2024/1/5") == "20240105"
assert _norm_date("2024-01-05 15:00:00") == "20240105"
assert _norm_date("无日期") == ""
print("[ok] 日期归一化多格式兼容")

# 8) as_of 缺失 / 无法解析 → 放行且标注
ra = guard_source("financial", fins, "")
assert ra["allowed"] and "as_of 未设置" in ra["reason"]
rb = guard_source("financial", fins, "not-a-date")
assert rb["allowed"] and "无法解析" in rb["reason"]
print("[ok] as_of 缺失/异常安全降级")

# 9) 数据源登记册
cat = sources_catalog()
assert len(cat) == 8
by = {c["source"]: c for c in cat}
assert by["financial"]["strict"] is True
assert by["news"]["strict"] is False
assert "ann_date" in by["financial"]["fields"]
print("[ok] 数据源登记册 %d 条（strict=%s）" %
      (len(cat), [c["source"] for c in cat if c["strict"]]))

# 10) 接入 pit_guard.guard_data 的源级守卫
from core.pit_guard import guard_data
g = guard_data("financial_tool", fins, AS_OF, source="financial")
assert g["allowed"] and g["kept"] == 1 and g["field"] == "ann_date"
gb = guard_data("financial_tool", bad, AS_OF, source="financial")
assert gb["allowed"] is False
# 不传 source → 仍走原有通用递归过滤（向后兼容）
gc = guard_data("news", {"rows": [{"date": "2024-01-01"}, {"date": "2024-12-31"}]}, AS_OF)
assert gc["allowed"] and gc["filtered"] >= 1
print("[ok] pit_guard.guard_data 源级守卫接入 + 向后兼容")

print("\nALL PASS")
