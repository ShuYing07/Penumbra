# -*- coding: utf-8 -*-
"""模块八：数据溯源与证据链测试。"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("STOCKAI_MOCK", "1")

from core.evidence_manager import (init, register_claim, save_report_evidence,
                                   get_evidence)
from core.data.cache import get_conn

# 0) 清理历史残留（测试幂等）
init()
with get_conn() as conn:
    conn.execute("DELETE FROM evidence WHERE analysis_id IN ('ev-001','ev-002','ev-003')")

# 1) 单条结论登记 + 回读
init()
register_claim("ev-001", 0, "RSI(14)=62.9 处于中性偏强区间",
               "RSI(14)", {"rsi14": 62.9, "asof": "2026-09-28"})
ev = get_evidence("ev-001")
assert len(ev) == 1 and ev[0]["source"] == "RSI(14)"
assert ev[0]["data_snapshot"]["rsi14"] == 62.9
print("[ok] 单条证据登记/回读")

# 2) 批量登记（模拟完整分析状态）+ 幂等
state = {
    "ticker": "SH600519", "asof": "2026-09-28",
    "quote": {"price": 1500.0, "chg_pct": 0.5},
    "tech": {"rsi14": 55.0, "chg_pct_1d": 0.5},
    "news": [{"published_at": "2026-09-27", "source": "新浪财经", "title": "示例"}],
    "signals": {"technical": {"stance": "看多", "view": "RSI中性偏强，根据近20日数据"},
                "fundamental": {"stance": "中性", "view": "数据不足"}},
    "bull_case": ["近20日涨幅+5%，超额沪深300 +3%（数据期：2026-08-01至2026-09-28）"],
    "bear_case": ["近60日回撤-8%（数据期：2026-06-01至2026-08-30）"],
    "trader": {"action": "观望"}, "risk": {"notes": ["无"]},
    "final": {"action": "观望", "summary": "示例"},
}
n = save_report_evidence("ev-002", state)
assert n >= 8, n
ev2 = get_evidence("ev-002")
assert len(ev2) == n
assert any(e["source"] == "多空辩论" and "bull_case" in e["data_snapshot"] for e in ev2)
assert any(e["source"] == "新闻管道" for e in ev2)
# 幂等：再存一次数量不变
save_report_evidence("ev-002", state)
assert len(get_evidence("ev-002")) == n
print(f"[ok] 批量证据登记（{n} 条）/幂等/辩论带引用")

# 3) 空状态安全
assert save_report_evidence("ev-003", {}) == 0
print("[ok] 空状态安全")

print("\nALL PASS")
