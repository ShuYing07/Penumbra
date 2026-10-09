# -*- coding: utf-8 -*-
"""PIT 时点基准测试集（point-in-time benchmark · 参考 quant-backtest-guard）。

为什么需要它
------------
前视偏差最隐蔽的形态不是代码里写了 ``shift(-1)``，而是**数据本身带未来**：
回测跑到 2024-03-01，财务库里却已经躺着 2023 年报（实际 2024-04-20 才公告）。
代码无罪，数据有毒——这类泄漏 AST 扫不出来，只能靠「已知真相的问答题」抓。

本模块提供一套**标准考题**：每道题都明确知道
「这条信息最早什么时候才该被看见」，然后双向验证：

- **泄漏测试**（as_of 早于信息日）：必须拿不到值 → 拿到了 = LEAK（致命）
- **可用测试**（as_of 晚于信息日）：必须拿得到值 → 拿不到 = MISSING（缺陷）

两类都跑，才能区分「数据带未来」和「数据根本没接上」。

八大事件族
----------
财报公告 / 分红除权 / 送转拆并 / 指数成分调整 / 停复牌 /
限售解禁 / 评级发布 / 名称与 ST 变更

用法
----
>>> from core.quant.pit_benchmark import run_benchmark, make_event_accessor
>>> acc = make_event_accessor(PIT_CASES)          # 标准（守规矩）实现
>>> rep = run_benchmark(acc)
>>> rep["leaked"], rep["passed"]
(0, True)

把 ``acc`` 换成你自己的数据访问层（``access(field, symbol, as_of)``），
即可在 CI 里给任意数据源打 PIT 分。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field as dc_field
from typing import Any, Callable, Dict, List, Optional, Sequence

log = logging.getLogger("stockai.quant.pit")

# 信息类型的中文名与「该用什么日期」的口径说明
CATEGORY_META: Dict[str, Dict[str, str]] = {
    "filing": {"name": "财报公告", "date_field": "announce_date",
               "rule": "以交易所实际披露日为准，绝不能用报告期期末日"},
    "dividend": {"name": "分红除权", "date_field": "ex_date",
                 "rule": "以除权除息日为准，预案日/股东大会日都不算落地"},
    "split": {"name": "送转拆并", "date_field": "effective_date",
              "rule": "以股本变动生效日为准"},
    "index": {"name": "指数成分调整", "date_field": "effective_date",
              "rule": "以调整生效日为准，公告日不能提前建仓"},
    "halt": {"name": "停复牌", "date_field": "resume_date",
             "rule": "停牌期间不可成交，复牌日才恢复"},
    "unlock": {"name": "限售解禁", "date_field": "unlock_date",
               "rule": "以解禁上市流通日为准"},
    "rating": {"name": "评级发布", "date_field": "publish_date",
               "rule": "以研报发布日为准，不能用报告内的数据截止日"},
    "rename": {"name": "名称/ST 变更", "date_field": "effective_date",
               "rule": "以变更生效日为准"},
}


@dataclass
class PITCase:
    """一道 PIT 考题。

    Attributes:
        id: 题目编号
        category: 事件族（见 CATEGORY_META）
        symbol: 标的代码
        field: 查询字段名
        info_date: 该信息**最早可被看见**的日期（YYYY-MM-DD）
        value: 该信息的真实值（as_of >= info_date 时应拿到）
        before: 泄漏测试用的 as_of（必须早于 info_date）
        after: 可用测试用的 as_of（必须 >= info_date）
        note: 背景说明（可选）
    """
    id: str
    category: str
    symbol: str
    field: str
    info_date: str
    value: Any
    before: str
    after: str
    note: str = ""
    tags: List[str] = dc_field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "category": self.category, "symbol": self.symbol,
                "field": self.field, "info_date": self.info_date,
                "value": self.value, "before": self.before, "after": self.after,
                "note": self.note, "tags": list(self.tags)}


def _c(i, cat, sym, fld, info, val, before, after, note="", tags=()):
    return PITCase(i, cat, sym, fld, info, val, before, after, note, list(tags))


# ---------------------------------------------------------------------------
# 内置标准考题（合成基线：事件日期与数值均为可复现的教学样本，
# 真实接入时请替换为公司自己的事件库，接口不变）
# ---------------------------------------------------------------------------
PIT_CASES: List[PITCase] = [
    # ---- 财报公告：最常见、最致命 ----
    _c("PIT-001", "filing", "600519", "net_profit_2023", "2024-04-20",
       74734000000.0, "2024-03-01", "2024-04-22",
       "2023 年报 4/20 披露，3 月回测绝不该看到净利润", ["年报", "高频踩坑"]),
    _c("PIT-002", "filing", "000858", "revenue_2023q3", "2023-10-31",
       30000000000.0, "2023-09-30", "2023-11-01",
       "三季报 10/31 披露，9/30 是报告期期末日不是可见日", ["季报"]),
    _c("PIT-003", "filing", "601318", "eps_2024q1", "2024-04-30",
       1.52, "2024-04-15", "2024-05-06",
       "一季报 4/30 披露，4 月中不得提前使用", ["季报"]),
    # ---- 分红除权 ----
    _c("PIT-004", "dividend", "600036", "dividend_per_share", "2024-07-10",
       1.972, "2024-06-20", "2024-07-11",
       "除权除息日 7/10，之前用预案金额属未来信息", ["除权"]),
    _c("PIT-005", "dividend", "601988", "adj_factor", "2024-06-28",
       0.9785, "2024-05-30", "2024-07-01",
       "复权因子随除权日跳变，提前应用会抹掉真实跌幅", ["复权"]),
    # ---- 送转拆并 ----
    _c("PIT-006", "split", "300750", "share_ratio", "2024-05-20",
       1.8, "2024-04-10", "2024-05-21",
       "10 转 8 于 5/20 生效，之前股本不变", ["股本"]),
    # ---- 指数成分调整 ----
    _c("PIT-007", "index", "688981", "in_index_000300", "2024-06-17",
       True, "2024-05-10", "2024-06-18",
       "沪深300 调样 6/17 生效，公告日建仓＝提前知道名单", ["调样"]),
    _c("PIT-008", "index", "002594", "in_index_000905", "2023-12-11",
       False, "2023-11-01", "2023-12-12",
       "被调出也是信息，不能沿用旧成分", ["调出"]),
    # ---- 停复牌 ----
    _c("PIT-009", "halt", "600122", "tradable", "2024-03-15",
       True, "2024-02-20", "2024-03-18",
       "停牌期间回测若照常成交＝假设流动性恒在", ["停牌"]),
    # ---- 限售解禁 ----
    _c("PIT-010", "unlock", "603259", "unlock_shares", "2024-08-05",
       120000000.0, "2024-06-01", "2024-08-06",
       "解禁规模在解禁日前不可用于预测抛压", ["解禁"]),
    # ---- 评级发布 ----
    _c("PIT-011", "rating", "000333", "analyst_rating", "2024-02-26",
       "买入", "2024-01-30", "2024-02-27",
       "研报发布日 ≠ 报告数据截止日", ["研报"]),
    # ---- 名称 / ST 变更 ----
    _c("PIT-012", "rename", "600242", "is_st", "2024-05-06",
       True, "2024-04-01", "2024-05-07",
       "ST 帽子戴上才叫 ST，提前剔除会污染股票池", ["ST"]),
]


# ---------------------------------------------------------------------------
# 访问器接口
# ---------------------------------------------------------------------------
def make_event_accessor(cases: Sequence[PITCase] = tuple(PIT_CASES),
                        leak: bool = False) -> Callable[[str, str, str], Any]:
    """构造一个参考访问器，用于自检与演示。

    Args:
        cases: 事件库
        leak: True 时返回**故意忽略 as_of** 的错误实现（模拟带未来的数据源），
              用于验证基准本身抓得住泄漏。
    """
    table: Dict[tuple, tuple] = {}          # (symbol, field) -> (info_date, value)
    for c in cases:
        table[(c.symbol, c.field)] = (c.info_date, c.value)

    def access(field_name: str, symbol: str, as_of: str) -> Any:
        row = table.get((symbol, field_name))
        if row is None:
            return None
        info_date, value = row
        if leak:
            return value                     # ❌ 无视 as_of —— 典型前视数据源
        return value if str(as_of) >= str(info_date) else None

    return access


# ---------------------------------------------------------------------------
# 评分
# ---------------------------------------------------------------------------
def _same(a: Any, b: Any) -> bool:
    if a is None and b is None:
        return True
    if isinstance(a, float) and isinstance(b, (int, float)):
        return abs(a - float(b)) < 1e-6 * max(1.0, abs(float(b)))
    return a == b


def run_case(accessor: Callable[[str, str, str], Any],
             case: PITCase) -> Dict[str, Any]:
    """跑一道题，返回 {id, category, leak_ok, avail_ok, status, detail}。"""
    out = {"id": case.id, "category": case.category, "symbol": case.symbol,
           "field": case.field, "info_date": case.info_date}
    try:
        got_before = accessor(case.field, case.symbol, case.before)
        got_after = accessor(case.field, case.symbol, case.after)
    except Exception as e:  # noqa: BLE001  访问器自身抛错也算失败
        out.update(leak_ok=False, avail_ok=False, status="ERROR",
                   detail=f"访问器异常：{type(e).__name__}: {e}")
        return out

    leak_ok = not _same(got_before, case.value)      # 早于信息日必须拿不到
    avail_ok = _same(got_after, case.value)          # 晚于信息日必须拿得到
    if not leak_ok:
        status = "LEAK"                              # 致命：数据带未来
    elif not avail_ok:
        status = "MISSING"                           # 缺陷：数据缺失/接错
    else:
        status = "PASS"
    out.update(leak_ok=leak_ok, avail_ok=avail_ok, status=status,
               got_before=got_before, got_after=got_after,
               detail=("泄漏：as_of=%s 已能取到 %s（信息日 %s）"
                       % (case.before, got_before, case.info_date)
                       if not leak_ok else
                       "缺失：as_of=%s 取不到应可见的 %s"
                       % (case.after, case.value) if not avail_ok else "通过"))
    return out


def run_benchmark(accessor: Callable[[str, str, str], Any],
                  cases: Sequence[PITCase] = tuple(PIT_CASES)) -> Dict[str, Any]:
    """跑完整基准。返回 {results, leaked, missing, passed, total, score, grade, summary}。"""
    results = [run_case(accessor, c) for c in cases]
    leaked = sum(1 for r in results if r["status"] == "LEAK")
    missing = sum(1 for r in results if r["status"] == "MISSING")
    errored = sum(1 for r in results if r["status"] == "ERROR")
    ok = sum(1 for r in results if r["status"] == "PASS")
    total = len(results) or 1
    score = round(ok / total, 4)
    if leaked:
        grade = "F"                       # 只要有一例泄漏，回测结论全废
    elif score >= 0.99:
        grade = "A"
    elif score >= 0.9:
        grade = "B"
    elif score >= 0.75:
        grade = "C"
    else:
        grade = "D"
    by_cat: Dict[str, Dict[str, int]] = {}
    for r in results:
        d = by_cat.setdefault(r["category"], {"total": 0, "pass": 0, "leak": 0})
        d["total"] += 1
        if r["status"] == "PASS":
            d["pass"] += 1
        elif r["status"] == "LEAK":
            d["leak"] += 1
    return {
        "results": results, "leaked": leaked, "missing": missing,
        "errored": errored, "passed": leaked == 0 and missing == 0 and errored == 0,
        "ok": ok, "total": len(results), "score": score, "grade": grade,
        "by_category": by_cat,
        "summary": (f"PIT 基准：{len(results)} 题 · 通过 {ok} / 泄漏 {leaked} / "
                    f"缺失 {missing} / 异常 {errored} · 得分 {score:.0%} · 评级 {grade}"),
    }


def estimate_leak_days(case: PITCase) -> int:
    """泄漏窗口天数：信息日 与 泄漏测试日 的间隔（衡量踩坑代价）。"""
    from datetime import date
    try:
        a = date.fromisoformat(case.before)
        b = date.fromisoformat(case.info_date)
        return max(0, (b - a).days)
    except (TypeError, ValueError):
        return 0


def format_report(rep: Dict[str, Any]) -> str:
    """人读报告：按事件族分组，突出泄漏项。"""
    lines = [rep["summary"], ""]
    for r in rep["results"]:
        mark = {"PASS": "✅", "LEAK": "⛔", "MISSING": "⚠️",
                "ERROR": "💥"}.get(r["status"], "·")
        cat = CATEGORY_META.get(r["category"], {}).get("name", r["category"])
        lines.append(f"{mark} {r['id']} [{cat}] {r['symbol']}.{r['field']} "
                     f"信息日 {r['info_date']} → {r['status']}")
        if r["status"] != "PASS":
            lines.append(f"     {r['detail']}")
    leaks = [r for r in rep["results"] if r["status"] == "LEAK"]
    if leaks:
        days = [estimate_leak_days(
            next(c for c in PIT_CASES if c.id == r["id"])) for r in leaks
            if any(c.id == r["id"] for c in PIT_CASES)]
        lines.append("")
        lines.append(f"⛔ {len(leaks)} 项信息泄漏"
                     + (f"，最长泄漏窗口 {max(days)} 天" if days else "")
                     + "：该数据源不可用于回测")
    return "\n".join(lines)


if __name__ == "__main__":
    good = run_benchmark(make_event_accessor())
    assert good["passed"] is True, good["summary"]
    assert good["grade"] == "A"
    bad = run_benchmark(make_event_accessor(leak=True))
    assert bad["leaked"] == len(PIT_CASES), bad["summary"]
    assert bad["grade"] == "F"
    assert bad["passed"] is False
    empty = run_benchmark(lambda f, s, d: None)
    assert empty["missing"] == len(PIT_CASES)
    print("pit_benchmark self-check ok:",
          good["summary"], "|", bad["summary"])
