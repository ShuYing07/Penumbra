# -*- coding: utf-8 -*-
"""港股 / ETF 市场覆盖单测：识别、时段、费率、整手、回测整手。可直接运行，也兼容 pytest。"""
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.config import BEIJING_TZ, is_market_open
from core.data.service import is_cn_etf, market_of, security_type
from core.quant.backtest import (BacktestConfig, _lot_shares, default_fee,
                                  run_backtest)


def _t(y, mo, d, h, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=BEIJING_TZ)


# ---------- 市场识别 ----------
def test_market_of_hk():
    assert market_of("0700.HK") == "HK"
    assert market_of("00700.HK") == "HK"     # 5 位数字
    assert market_of("02800.HK") == "HK"
    # 其他后缀仍落 GLOBAL
    assert market_of("7203.T") == "GLOBAL"
    assert market_of("AAPL") == "US"
    assert market_of("BTC-USD") == "CRYPTO"
    assert market_of("SH600519") == "CN"


def test_is_cn_etf():
    assert is_cn_etf("SH510300")      # 沪深300ETF
    assert is_cn_etf("SH588000")      # 科创50ETF
    assert is_cn_etf("SZ159915")      # 创业板ETF
    assert not is_cn_etf("SH600519")  # 贵州茅台
    assert not is_cn_etf("SZ000001")  # 平安银行
    assert not is_cn_etf("SH51030")   # 仅 5 位数字
    assert not is_cn_etf("0700.HK")


def test_security_type():
    assert security_type("SH510300") == "ETF"
    assert security_type("SH600519") == "STOCK"
    assert security_type("0700.HK") == "STOCK"
    assert security_type("SPY") == "STOCK"      # 美股 ETF 不区分（费率同股票）


# ---------- 港股时段（北京时间 = 港股本地时间）----------
def test_market_open_hk():
    assert _t(2026, 9, 14, 0).weekday() == 0   # 确认是周一
    assert is_market_open("HK", _t(2026, 9, 14, 10, 0)) is True   # 上午
    assert is_market_open("HK", _t(2026, 9, 14, 11, 59)) is True
    assert is_market_open("HK", _t(2026, 9, 14, 12, 30)) is False  # 午休
    assert is_market_open("HK", _t(2026, 9, 14, 14, 0)) is True    # 下午
    assert is_market_open("HK", _t(2026, 9, 14, 16, 0)) is False   # 收盘（边界）
    assert is_market_open("HK", _t(2026, 9, 12, 10, 0)) is False   # 周六


# ---------- 费率 ----------
def test_default_fee_hk():
    f = default_fee("HK")
    assert f.stamp_tax_sell == 0.0013
    assert f.transfer_fee == 0.00003
    assert f.commission_rate == 0.0003 and f.min_commission == 0.0
    # 卖出费含印花税+双边杂费
    assert f.sell_fee(100000) >= 100000 * 0.0013


def test_default_fee_cn_etf_exempt():
    etf = default_fee("CN", "SH510300")
    assert etf.stamp_tax_sell == 0.0 and etf.transfer_fee == 0.0
    assert etf.commission_rate == 0.00025      # 佣金仍收
    stock = default_fee("CN", "SH600519")
    assert stock.stamp_tax_sell == 0.0005 and stock.transfer_fee == 0.00001


def test_default_fee_others_unchanged():
    assert default_fee("US").stamp_tax_sell == 0.0
    assert default_fee("CRYPTO").commission_rate == 0.001


# ---------- 整手 ----------
def test_lot_shares_hk_and_cn():
    # 15000 元 / 100 元 = 150 股 → 整手向下取 100
    assert _lot_shares("HK", 15000, 100) == 100.0
    assert _lot_shares("CN", 15000, 100) == 100.0
    assert _lot_shares("HK", 9999, 100) == 0.0          # 不足 1 手
    # 美股碎股 4 位、加密 6 位
    assert _lot_shares("US", 15000, 100) == 150.0
    assert _lot_shares("CRYPTO", 15000, 100) == 150.0


def test_backtest_hk_roundtrip_lot100():
    """港股回测 buy_hold：买入股数必须是 100 的整倍数，费率走港股默认。"""
    idx = pd.date_range("2026-01-01", periods=40, freq="B")
    closes = [100.0] * 40
    df = pd.DataFrame({
        "open": closes, "high": [c * 1.01 for c in closes],
        "low": [c * 0.99 for c in closes], "close": closes,
        "volume": [1000] * 40, "amount": [0.0] * 40,
    }, index=idx)
    cfg = BacktestConfig(ticker="0700.HK", market="HK", init_capital=1_000_000)
    assert cfg.resolve_fee().stamp_tax_sell == 0.0013
    res = run_backtest(df, "HK", "buy_hold", {}, cfg)
    buys = res.trades[res.trades["side"] == "买入"]
    assert len(buys) == 1
    qty = float(buys.iloc[0]["shares"])
    assert qty > 0 and qty % 100 == 0


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        fn()
        print(f"  PASS {fn.__name__}")
        passed += 1
    print(f"\n{passed}/{len(fns)} 个市场覆盖测试通过")


if __name__ == "__main__":
    _run_all()
