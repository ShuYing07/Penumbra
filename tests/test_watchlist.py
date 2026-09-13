# -*- coding: utf-8 -*-
"""自选股盯盘单测：条件解析、评估、交易时段、持久化 CRUD。可直接运行，也兼容 pytest。"""
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.config import BEIJING_TZ, is_market_open, refresh_interval
from core.watchlist import conditions, store
from core.watchlist.conditions import evaluate, parse, preview

import core.data.cache as _cache


def _t(y, mo, d, h, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=BEIJING_TZ)


# ---------- 归一化 ----------
def test_normalize_cn_digits():
    assert conditions.normalize("RSI大于七") == "rsi大于7"
    assert conditions.normalize("涨幅超过５％") == "涨幅超过5%"
    assert conditions.normalize(" 跌破 20 日线 ") == "跌破20日线"


def test_normalize_ten_combination():
    assert conditions.normalize("RSI大于二十") == "rsi大于20"
    assert conditions.normalize("RSI大于二十三") == "rsi大于23"


# ---------- 解析 ----------
def test_parse_price_ma_breakdown():
    c = parse("跌破20日线")
    assert c.kind == "price" and c.field == "MA20" and c.op == "cross_down"
    assert c.error is None


def test_parse_price_ma_breakthrough():
    c = parse("现价突破MA5")
    assert c.kind == "price" and c.field == "MA5" and c.op == "cross_up"


def test_parse_price_ma_with_op():
    c = parse("大于20日线")
    assert c.kind == "price" and c.field == "MA20" and c.op == "gt"


def test_parse_price_value():
    c = parse("现价大于100元")
    assert c.kind == "price" and c.field == "price" and c.op == "gt" and c.value == 100


def test_parse_rsi():
    c = parse("RSI大于70")
    assert c.kind == "rsi" and c.field == "rsi14" and c.op == "gt" and c.value == 70


def test_parse_chgpct_up():
    c = parse("涨幅超过5%")
    assert c.kind == "chgpct" and c.op == "gt" and c.value == 5 and c.direction == "up"


def test_parse_chgpct_down():
    c = parse("跌幅超过3%")
    assert c.kind == "chgpct" and c.direction == "down" and c.value == 3


def test_parse_macd():
    assert parse("MACD金叉").value == "MACD金叉"
    assert parse("macd死叉").value == "MACD死叉"


def test_parse_volume_amplify():
    c = parse("成交量放大2倍")
    assert c.kind == "volume" and c.op == "gt" and c.value == 2


def test_parse_volume_shrink():
    c = parse("成交量缩量")
    assert c.kind == "volume" and c.op == "lt" and c.value == 1.0


def test_parse_suffix_stripped():
    c = parse("rsi大于70提醒")
    assert c.kind == "rsi" and c.error is None


def test_parse_unknown():
    c = parse("rsi过高")
    assert c.kind is None and c.error is not None and "支持语法" in c.error


def test_parse_empty():
    assert parse("").error is not None
    assert parse("   ").error is not None


def test_preview_invalid():
    assert "❌" in preview("rsi过高")
    assert "✅" in preview("RSI大于70")


# ---------- 评估 ----------
def _snap(ma20=10.0, prev_close=10.5, close=9.0, rsi14=None, vol=None, signal=None, chg=None):
    return {
        "ma": {"MA20": ma20, "MA5": ma20, "MA10": ma20, "MA60": ma20},
        "prev_close": prev_close, "close": close, "rsi14": rsi14,
        "vol_ratio_5_20": vol, "chg_pct_1d": chg,
        "macd": {"signal": signal},
    }


def test_evaluate_price_breakdown_trigger():
    cond = parse("跌破20日线")
    r = evaluate(cond, _snap(ma20=10, prev_close=10.5, close=9.5), {"price": 9.0})
    assert r.triggered and r.status == "✅触发" and "-10.00%" in r.distance


def test_evaluate_price_breakdown_no_penetration():
    cond = parse("跌破20日线")
    # 现价=10.5 未跌破，前收 10.8 也在上方 → 未穿透
    r = evaluate(cond, _snap(ma20=10, prev_close=10.8, close=10.5), {"price": 10.5})
    assert not r.triggered and r.status == "⏳等待"


def test_evaluate_price_gt():
    cond = parse("大于20日线")
    r = evaluate(cond, _snap(ma20=10, close=11), {"price": 11})
    assert r.triggered


def test_evaluate_rsi_trigger():
    r = evaluate(parse("RSI大于70"), _snap(rsi14=75), {})
    assert r.triggered and "75.0" in r.distance


def test_evaluate_chgpct_up():
    r = evaluate(parse("涨幅超过5%"), _snap(), {"chg_pct": 6.0})
    assert r.triggered


def test_evaluate_chgpct_down():
    # 跌幅超过3%：chg=-4 → 跌幅=4 > 3
    r = evaluate(parse("跌幅超过3%"), _snap(), {"chg_pct": -4.0})
    assert r.triggered


def test_evaluate_macd_match():
    r = evaluate(parse("MACD金叉"), _snap(signal="MACD金叉"), {})
    assert r.triggered
    r2 = evaluate(parse("MACD金叉"), _snap(signal="MACD死叉"), {})
    assert not r2.triggered and r2.status == "⏳等待"


def test_evaluate_volume():
    r = evaluate(parse("成交量放大2倍"), _snap(vol=2.5), {})
    assert r.triggered


def test_evaluate_no_data():
    r = evaluate(parse("RSI大于70"), {}, {})
    assert r.status == "—无数据" and not r.triggered


def test_evaluate_invalid_cond():
    r = evaluate(parse("rsi过高"), _snap(), {})
    assert r.status == "❌无效"


# ---------- 交易时段 ----------
def test_market_open_cn():
    assert is_market_open("CN", _t(2026, 9, 14, 10, 0)) is True   # 周一上午
    assert is_market_open("CN", _t(2026, 9, 14, 14, 0)) is True   # 周一下午
    assert is_market_open("CN", _t(2026, 9, 14, 12, 0)) is False  # 午间休市
    assert is_market_open("CN", _t(2026, 9, 12, 10, 0)) is False  # 周六


def test_market_open_us_summer():
    # 9 月=夏令时；周一 21:00 未开盘，21:30 开盘
    assert is_market_open("US", _t(2026, 9, 14, 21, 0)) is False
    assert is_market_open("US", _t(2026, 9, 14, 21, 30)) is True
    assert is_market_open("US", _t(2026, 9, 14, 22, 0)) is True
    # 周二凌晨 03:00 属周一晚盘延伸
    assert is_market_open("US", _t(2026, 9, 15, 3, 0)) is True


def test_market_open_us_winter():
    # 12 月=冬令时；周一 22:00 未开盘，22:30 开盘
    assert is_market_open("US", _t(2026, 12, 14, 22, 0)) is False
    assert is_market_open("US", _t(2026, 12, 14, 22, 30)) is True


def test_market_open_crypto_and_global():
    assert is_market_open("CRYPTO", _t(2026, 9, 13, 3, 0)) is True
    assert is_market_open("GLOBAL", _t(2026, 9, 14, 10, 0)) is False


def test_refresh_interval():
    assert refresh_interval("CRYPTO") == 60
    assert refresh_interval("CN", _t(2026, 9, 14, 10, 0)) == 60   # 盘中
    assert refresh_interval("CN", _t(2026, 9, 14, 12, 0)) == 300  # 盘外
    assert refresh_interval("CN", _t(2026, 9, 12, 10, 0)) == 300  # 周末


# ---------- 持久化 ----------
def _tmp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return path


def test_store_crud():
    path = _tmp_db()
    old = _cache.DB_PATH
    _cache.DB_PATH = path
    try:
        store.init()
        assert store.add("SH600519", "CN", "RSI大于70") is True
        assert store.add("SH600519", "CN") is False          # 重复
        rows = store.list_all()
        assert len(rows) == 1 and rows[0]["ticker"] == "SH600519"
        assert rows[0]["condition"] == "RSI大于70" and rows[0]["enabled"] is True
        assert len(store.list_enabled()) == 1
        store.update("sh600519", condition="MACD金叉")
        assert store.get("SH600519")["condition"] == "MACD金叉"
        store.set_enabled("SH600519", False)
        assert store.list_enabled() == [] and len(store.list_all()) == 1
        store.set_last_trigger("SH600519")
        assert store.get("SH600519")["last_trigger_at"] is not None
        store.remove("SH600519")
        assert store.list_all() == []
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
    print(f"\n{passed}/{len(fns)} 个盯盘测试通过")


if __name__ == "__main__":
    _run_all()
