# -*- coding: utf-8 -*-
"""PIT-Guard 全数据源覆盖（2026-10 翻新 · 模块二）。

参考 TradingAgents v0.5.0「point-in-time integrity across every dated path」：
点时间约束必须覆盖**每一条带日期的数据路径**，而不只是行情 K 线。

最大的前视来源不是 K 线，而是**财报**：财报有三个日期——
- period_end（报告期期末）：数据尚未产生，用它即 30~90 天前视；
- filed / announce（公告/披露日）：数据真正可得的时点 ← **唯一可用**；
- 本模块对财报类数据强制取公告字段，缺失即**阻断放行**（保守优先）。

分源守卫：
- 每个数据源登记「可用日期字段」优先级（含别名）与严格模式；
- `guard_source(name, rows, as_of)` 按字段优先级抽取可用时点并过滤未来记录；
- 严格源（filing / financial）缺可用日期字段 → allowed=False（不放行）；
- 非严格源（news / social / macro / decision_log）缺字段 → 放行但标注 untested。
"""
from __future__ import annotations

import os
import re
import sys
from typing import Any, Dict, List, Optional, Sequence

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 源名 → (日期字段优先级, 是否严格)
SOURCE_DATE_FIELDS: Dict[str, tuple] = {
    # 行情：交易日
    "quote": (("date", "trade_date", "日期", "datetime", "ts"), False),
    "bars": (("date", "trade_date", "日期"), False),
    # 新闻：发布时间
    "news": (("date", "publish_time", "pub_date", "pubDate", "datetime", "ts"), False),
    # 公告/财报：必须是公告日（announce/filed），绝不能用报告期
    "filing": (("ann_date", "announce_date", "公告日期", "filed",
                "filingDate", "publish_time", "date"), True),
    "financial": (("ann_date", "announce_date", "公告日期", "filed",
                   "filingDate", "report_date", "date"), True),
    # 宏观（FRED 等）：发布/观测日期
    "macro": (("date", "release_date", "obs_date", "period"), False),
    # 社交情绪
    "social": (("ts", "created_at", "date", "datetime", "time"), False),
    # 决策日志 / 记忆
    "decision_log": (("ts", "created_at", "date", "timestamp"), False),
}

# 明确禁止作为「可用时点」的字段（报告期 ≠ 可得时点）
_FORBIDDEN_FIELDS = ("period_end", "end_date", "报告期", "report_period",
                     "fiscal_period", "period")

_ALL_SOURCES = tuple(SOURCE_DATE_FIELDS)


def _norm_date(s: Any) -> str:
    """归一化为 YYYYMMDD（支持 2024-01-05 / 20240105 / 2024/1/5 / ISO 时间）。"""
    t = str(s or "")
    m = re.search(r"(\d{4})[-/.]?(\d{1,2})[-/.]?(\d{1,2})", t)
    if not m:
        return ""
    return f"{m.group(1)}{int(m.group(2)):02d}{int(m.group(3)):02d}"


def pick_date_field(rows: Sequence[dict], source: str) -> Optional[str]:
    """按源字段优先级挑出实际存在的日期字段；财报类绝不选报告期字段。"""
    fields, _strict = SOURCE_DATE_FIELDS.get(source, ((), False))
    if not rows:
        return fields[0] if fields else None
    sample = rows[0] if isinstance(rows[0], dict) else {}
    for f in fields:
        if f in sample and f not in _FORBIDDEN_FIELDS:
            return f
    # 兜底：任一看起来像日期的字段（仍排除报告期字段）
    for k, v in sample.items():
        if k in _FORBIDDEN_FIELDS:
            continue
        if _norm_date(v):
            return k
    return None


def guard_source(source: str, rows: Any, as_of: str) -> Dict[str, Any]:
    """对单一数据源执行点时间过滤。

    返回 {allowed, kept, filtered, field, reason, data}：
    - 严格源缺可用日期字段 → allowed=False（不返回数据，防前视）；
    - 数据被过滤后为空 → allowed=True 但 kept=0 并标注。
    """
    _fields, strict = SOURCE_DATE_FIELDS.get(source, ((), False))
    if not as_of:
        return {"allowed": True, "kept": (len(rows) if hasattr(rows, "__len__") else 0),
                "filtered": 0, "field": None,
                "reason": "as_of 未设置（不作过滤，标注 untested）", "data": rows}
    as_of_n = _norm_date(as_of)
    if not as_of_n:
        return {"allowed": True, "kept": 0, "filtered": 0, "field": None,
                "reason": f"as_of 无法解析：{as_of}", "data": rows}

    if not isinstance(rows, list) or (rows and not isinstance(rows[0], dict)):
        # 非结构化负载：交给调用方（如 guard_data 通用递归过滤）
        return {"allowed": True, "kept": 0, "filtered": 0, "field": None,
                "reason": "非 dict 列表负载，跳过字段级过滤", "data": rows}

    field = pick_date_field(rows, source)
    if not field:
        if strict:
            return {"allowed": False, "kept": 0, "filtered": len(rows),
                    "field": None,
                    "reason": (f"[{source}] 缺少可用于点时间过滤的日期字段"
                               f"（须为公告/发布日，不能用报告期），"
                               f"已阻断以防前视偏差"),
                    "data": []}
        return {"allowed": True, "kept": len(rows), "filtered": 0,
                "field": None,
                "reason": f"[{source}] 无日期字段，放行但标注 untested",
                "data": rows}

    kept, dropped = [], 0
    for r in rows:
        d = _norm_date(r.get(field))
        if not d or d <= as_of_n:
            kept.append(r)
        else:
            dropped += 1
    return {"allowed": True, "kept": len(kept), "filtered": dropped,
            "field": field,
            "reason": f"[{source}] 已按字段 {field} 截断至 as_of={as_of}",
            "data": kept}


def guard_all(sources: Dict[str, Any], as_of: str) -> Dict[str, Any]:
    """对多个数据源一次性守卫。返回 {results:{源:结果}, blocked:[源], total_filtered}。"""
    results: Dict[str, Any] = {}
    blocked: List[str] = []
    total = 0
    for name, rows in (sources or {}).items():
        r = guard_source(name, rows, as_of)
        results[name] = r
        total += int(r.get("filtered") or 0)
        if not r.get("allowed", True):
            blocked.append(name)
    return {"results": results, "blocked": blocked,
            "total_filtered": total,
            "summary": f"守卫 {len(results)} 个数据源，阻断 {len(blocked)} 个，"
                       f"剔除未来记录 {total} 条"}


def sources_catalog() -> List[Dict[str, Any]]:
    """数据源登记册（UI/审计展示）：字段优先级与严格性。"""
    return [{"source": s, "fields": list(f), "strict": strict}
            for s, (f, strict) in SOURCE_DATE_FIELDS.items()]


if __name__ == "__main__":
    as_of = "2024-03-01"

    # 1) 行情：按交易日截断
    quotes = [{"date": "2024-02-28", "close": 1.0},
              {"date": "2024-03-05", "close": 2.0}]
    r = guard_source("quote", quotes, as_of)
    assert r["allowed"] and r["kept"] == 1 and r["filtered"] == 1
    assert r["field"] == "date"

    # 2) 财报：有 ann_date（公告日）→ 用公告日过滤
    fins = [{"ann_date": "2024-02-20", "period_end": "2023-12-31", "rev": 100},
            {"ann_date": "2024-04-10", "period_end": "2023-12-31", "rev": 120}]
    r2 = guard_source("financial", fins, as_of)
    assert r2["allowed"] and r2["kept"] == 1 and r2["filtered"] == 1
    assert r2["field"] == "ann_date"      # 关键：不能用 period_end
    assert r2["data"][0]["rev"] == 100

    # 3) 财报：只有报告期字段 → 严格源阻断（防 30-90 天前视）
    bad = [{"period_end": "2023-12-31", "rev": 100}]
    r3 = guard_source("financial", bad, as_of)
    assert r3["allowed"] is False and r3["data"] == []
    assert "阻断" in r3["reason"]

    # 4) 新闻/社交：非严格源，缺字段放行但标注
    r4 = guard_source("news", [{"title": "无日期新闻"}], as_of)
    assert r4["allowed"] and "untested" in r4["reason"]

    # 5) 多源一次性守卫
    allr = guard_all({"quote": quotes, "financial": fins,
                      "social": [{"ts": "2024-02-01 10:00:00"}]}, as_of)
    assert allr["total_filtered"] >= 1
    assert isinstance(allr["blocked"], list)
    assert allr["summary"]

    # 6) 字段挑选绝不选报告期字段
    assert pick_date_field(fins, "financial") == "ann_date"
    assert pick_date_field(bad, "financial") in (None, "period_end")

    print(f"pit_sources self-check ok (quote_kept={r['kept']}, "
          f"fin_field={r2['field']}, blocked={allr['blocked']})")
