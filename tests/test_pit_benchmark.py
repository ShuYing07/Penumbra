# -*- coding: utf-8 -*-
"""core/quant/pit_benchmark.py PIT 时点基准单测。

重点验证：守规矩的数据源拿 A、故意泄漏的数据源必被抓（F）、
数据缺失与异常访问器分别识别、报告可读、泄漏窗口计算正确。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.quant import pit_benchmark as pb


# --------------------------------------------------------------------------
# 题库本身
# --------------------------------------------------------------------------
def test_cases_wellformed():
    assert len(pb.PIT_CASES) >= 12
    seen = set()
    for c in pb.PIT_CASES:
        assert c.id not in seen
        seen.add(c.id)
        assert c.category in pb.CATEGORY_META, c.category
        assert c.before < c.info_date <= c.after, c.id
        assert c.value is not None


def test_all_eight_categories_covered():
    cats = {c.category for c in pb.PIT_CASES}
    assert cats == set(pb.CATEGORY_META.keys()), cats - set(pb.CATEGORY_META)


def test_category_meta_has_rule():
    for k, v in pb.CATEGORY_META.items():
        assert v["name"] and v["date_field"] and v["rule"]


def test_as_dict_roundtrip():
    d = pb.PIT_CASES[0].as_dict()
    assert d["id"] == pb.PIT_CASES[0].id
    assert isinstance(d["tags"], list)


# --------------------------------------------------------------------------
# 标准访问器 → A 级
# --------------------------------------------------------------------------
def test_clean_accessor_passes():
    rep = pb.run_benchmark(pb.make_event_accessor())
    assert rep["passed"] is True
    assert rep["leaked"] == 0 and rep["missing"] == 0
    assert rep["score"] == 1.0 and rep["grade"] == "A"
    assert rep["total"] == len(pb.PIT_CASES)


def test_clean_accessor_by_category():
    rep = pb.run_benchmark(pb.make_event_accessor())
    assert sum(v["total"] for v in rep["by_category"].values()) == rep["total"]
    assert all(v["leak"] == 0 for v in rep["by_category"].values())


# --------------------------------------------------------------------------
# 泄漏访问器 → 必被抓
# --------------------------------------------------------------------------
def test_leaky_accessor_caught():
    rep = pb.run_benchmark(pb.make_event_accessor(leak=True))
    assert rep["leaked"] == len(pb.PIT_CASES)
    assert rep["grade"] == "F"
    assert rep["passed"] is False
    for r in rep["results"]:
        assert r["status"] == "LEAK"
        assert r["leak_ok"] is False


def test_partial_leak_still_f():
    """只有一题泄漏 → 依然 F（一例泄漏即全废）。"""
    base = pb.make_event_accessor()

    def half_leak(f, s, as_of):
        if s == "600519":          # 只在这一只上泄漏
            return base(f, s, "2099-01-01")
        return base(f, s, as_of)

    rep = pb.run_benchmark(half_leak)
    assert rep["leaked"] == 1
    assert rep["grade"] == "F"
    assert rep["score"] < 1.0


# --------------------------------------------------------------------------
# 缺失 / 异常
# --------------------------------------------------------------------------
def test_empty_accessor_is_missing_not_leak():
    rep = pb.run_benchmark(lambda f, s, d: None)
    assert rep["missing"] == len(pb.PIT_CASES)
    assert rep["leaked"] == 0
    assert rep["passed"] is False


def test_broken_accessor_is_error():
    def boom(f, s, d):
        raise RuntimeError("db down")

    rep = pb.run_benchmark(boom)
    assert rep["errored"] == len(pb.PIT_CASES)
    assert rep["passed"] is False
    assert "异常" in rep["results"][0]["detail"]


def test_float_tolerance():
    got = pb.run_case(pb.make_event_accessor(), pb.PIT_CASES[0])
    assert got["status"] == "PASS"
    assert pb._same(74734000000.0, 74734000000.0 + 1e-3)


# --------------------------------------------------------------------------
# 单题 / 窗口 / 报告
# --------------------------------------------------------------------------
def test_run_case_statuses():
    acc = pb.make_event_accessor(leak=True)
    r = pb.run_case(acc, pb.PIT_CASES[3])
    assert r["status"] == "LEAK" and "泄漏" in r["detail"]
    r2 = pb.run_case(lambda f, s, d: None, pb.PIT_CASES[3])
    assert r2["status"] == "MISSING" and "缺失" in r2["detail"]


def test_leak_window_days():
    c = pb.PIT_CASES[0]        # before=2024-03-01, info=2024-04-20
    assert pb.estimate_leak_days(c) == 50


def test_leak_window_zero_on_bad_date():
    c = pb.PIT_CASES[0]
    c2 = pb.PIT_CASES[0]
    old = c2.before
    try:
        c2.before = "not-a-date"
        assert pb.estimate_leak_days(c2) == 0
    finally:
        c2.before = old


def test_format_report_marks_leak():
    rep = pb.run_benchmark(pb.make_event_accessor(leak=True))
    txt = pb.format_report(rep)
    assert "⛔" in txt and "泄漏" in txt
    assert "不可用于回测" in txt


def test_format_report_clean():
    rep = pb.run_benchmark(pb.make_event_accessor())
    txt = pb.format_report(rep)
    assert "✅" in txt and "⛔" not in txt


if __name__ == "__main__":
    for name, fn in sorted(list(globals().items())):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok  {name}")
    print("ALL OK")
