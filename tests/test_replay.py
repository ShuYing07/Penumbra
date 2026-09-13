# -*- coding: utf-8 -*-
"""AI 信号历史回放单测：选点、时点切片、方向评估、独立表隔离、统计。可直接运行。"""
import os
import sys
import tempfile
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import core.data.cache as _cache
from core.agents import graph as graph_mod
from core.data import service
from core.llm import LLMRunner
from core.replay import engine, store


def _bars(n=300, closes=None, start="2024-01-01"):
    idx = pd.bdate_range(start, periods=n)
    closes = closes or [10.0] * n
    return pd.DataFrame({
        "open": closes, "high": [c * 1.01 for c in closes],
        "low": [c * 0.99 for c in closes], "close": closes,
        "volume": [1000.0] * n, "amount": [0.0] * n,
    }, index=idx)


def _tmp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return path


# ---------- 选点 ----------
def test_pick_dates_basic():
    bars = _bars(300)
    pts = engine.pick_dates(bars, step_bars=20, min_warmup=120, min_forward=20)
    # first=120, last_ok=280 → 120,140,...,260 共 8 点
    assert len(pts) == 8
    assert pts[0] == bars.index[120].strftime("%Y-%m-%d")
    assert pts[-1] == bars.index[260].strftime("%Y-%m-%d")
    # 末点后至少还有 20 根
    assert (len(bars) - 1) - bars.index.get_loc(pd.Timestamp(pts[-1])) >= 20


def test_pick_dates_insufficient():
    bars = _bars(50)
    try:
        engine.pick_dates(bars)
        assert False, "应抛 ValueError"
    except ValueError:
        pass


def test_pick_dates_end_clipping():
    bars = _bars(300)
    end = bars.index[150].strftime("%Y-%m-%d")
    pts = engine.pick_dates(bars, end=end, step_bars=10, min_warmup=120, min_forward=20)
    # last_ok=min(151, 280)=151 → 点 120,130,140,150
    assert len(pts) == 4 and pts[-1] == bars.index[150].strftime("%Y-%m-%d")


# ---------- 时点切片 ----------
def test_gather_facts_asof_slice():
    bars = _bars(300)
    asof = bars.index[150].strftime("%Y-%m-%d")
    news = [
        {"title": "旧闻", "published_at": f"{asof} 09:00:00"},
        {"title": "更早", "published_at": "2023-01-01 08:00:00"},
        {"title": "未来新闻", "published_at": bars.index[200].strftime("%Y-%m-%d")},
        {"title": "无日期", "published_at": ""},
    ]
    orig = (service.get_daily, service.get_fundamentals, service.get_news)
    service.get_daily = lambda t: (bars, "test")
    service.get_fundamentals = lambda t: {"name": "测试股"}
    service.get_news = lambda t: news
    try:
        state = graph_mod.gather_facts("SH600519", as_of=asof)
        assert state["asof"] == asof
        assert state["quote"]["date"] == asof
        assert state["quote"]["price"] == 10.0
        assert state["history"] == []                  # 回放不注入未来反思
        assert state["funda"].get("_as_of_note")       # 基本面局限标注
        titles = [n["title"] for n in state["news"]]
        assert "未来新闻" not in titles and "无日期" not in titles
        assert set(titles) == {"旧闻", "更早"}
        assert state["tech"]["asof"] == asof
    finally:
        service.get_daily, service.get_fundamentals, service.get_news = orig


# ---------- 不污染真实 decisions ----------
def test_replay_does_not_pollute_decisions():
    path = _tmp_db()
    old = _cache.DB_PATH
    _cache.DB_PATH = path
    bars = _bars(300)
    orig_daily = service.get_daily
    orig_news = service.get_news
    orig_funda = service.get_fundamentals
    service.get_daily = lambda t: (bars, "test")
    service.get_news = lambda t: []
    service.get_fundamentals = lambda t: {"name": "测试股"}
    try:
        from core.data.cache import get_conn
        from core.memory.decision_log import init as dl_init
        dl_init()
        with get_conn() as conn:
            before = conn.execute("SELECT COUNT(*) FROM decisions").fetchone()[0]
        runner = LLMRunner(mock=True)
        for p in (120, 140):
            asof = bars.index[p].strftime("%Y-%m-%d")
            final = engine.run_one("SH600519", asof, runner)
            assert final.get("action")
        with get_conn() as conn:
            after = conn.execute("SELECT COUNT(*) FROM decisions").fetchone()[0]
        assert before == after == 0, "回放不得写 decisions 表"
    finally:
        _cache.DB_PATH = old
        service.get_daily, service.get_news, service.get_fundamentals = (
            orig_daily, orig_news, orig_funda)
        os.remove(path)


# ---------- 评估方向 ----------
def _seed_batch(tmp_db, bars, batch_id, records):
    """records: [(asof_pos, action)]"""
    store.init()
    for pos, action in records:
        asof = bars.index[pos].strftime("%Y-%m-%d")
        store.save_signal(
            batch_id, "SH600519", "CN", "mock(规则桩)", asof,
            {"price": float(bars["close"].iloc[pos]), "action": action,
             "confidence": 55, "position_pct": 0})


def test_evaluate_directions():
    path = _tmp_db()
    old = _cache.DB_PATH
    _cache.DB_PATH = path
    # 前200根=12，后100根=10（i=200 起下跌）
    bars = _bars(300, closes=[12.0] * 200 + [10.0] * 100)
    try:
        bid = "TESTEVAL"
        _seed_batch(path, bars, bid, [
            (195, "卖出"),    # 5日后跌破：ret≈-16.67% → 命中
            (50, "买入"),     # 横盘期买入：ret=0 → 不命中
            (100, "观望"),    # 横盘 → hit=None
            (295, "买入"),    # 尾部：5日数据都不足 → 不评估
        ])
        n = engine.evaluate_batch(bid, bars)
        rows = {r["asof"] + r["action"]: r for r in store.list_batch(bid)}
        sell = rows[bars.index[195].strftime("%Y-%m-%d") + "卖出"]
        buy = rows[bars.index[50].strftime("%Y-%m-%d") + "买入"]
        wait = rows[bars.index[100].strftime("%Y-%m-%d") + "观望"]
        tail = rows[bars.index[295].strftime("%Y-%m-%d") + "买入"]
        assert sell["hit_5"] == 1 and sell["ret_5"] < 0
        assert buy["hit_5"] == 0 and buy["ret_5"] == 0
        assert wait["hit_10"] is None and wait["ret_10"] == 0
        assert tail["ret_5"] is None and tail["evaluated"] == 0
        assert n == 3
    finally:
        _cache.DB_PATH = old
        os.remove(path)


def test_store_roundtrip_and_stats():
    path = _tmp_db()
    old = _cache.DB_PATH
    _cache.DB_PATH = path
    bars = _bars(300, closes=[12.0] * 200 + [10.0] * 100)
    try:
        bid = "TESTSTAT"
        _seed_batch(path, bars, bid, [(195, "卖出"), (50, "买入"), (100, "观望")])
        engine.evaluate_batch(bid, bars)
        st = engine.batch_stats(bid)
        assert st["n"] == 3
        assert st["distribution"] == {"多": 1, "空": 1, "中性": 1, "错误": 0}
        h5 = st["horizons"][5]
        assert h5["directional"] == 2          # 观望不计方向
        assert h5["win_rate_pct"] == 50.0      # 卖中买错(横盘)
        assert h5["long_n"] == 1 and h5["short_n"] == 1
        batches = store.batches()
        assert any(b["batch_id"] == bid for b in batches)
    finally:
        _cache.DB_PATH = old
        os.remove(path)


def test_error_row_excluded():
    path = _tmp_db()
    old = _cache.DB_PATH
    _cache.DB_PATH = path
    bars = _bars(300)
    try:
        store.init()
        store.save_signal("TERR", "SH600519", "CN", "mock", "2024-06-01",
                          {}, error="ValueError: x")
        st = engine.batch_stats("TERR")
        assert st["distribution"]["错误"] == 1
        assert engine.evaluate_batch("TERR", bars) == 0
    finally:
        _cache.DB_PATH = old
        os.remove(path)


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        fn()
        print(f"  PASS {fn.__name__}")
        passed += 1
    print(f"\n{passed}/{len(fns)} 个回放测试通过")


if __name__ == "__main__":
    _run_all()
