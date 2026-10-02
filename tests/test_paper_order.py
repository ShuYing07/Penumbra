# -*- coding: utf-8 -*-
"""高保真模拟交易引擎单测：市价/限价/止损 + 佣金/印花税/滑点 + 整手规则。"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("STOCKAI_MOCK", "1")
# 隔离 DB：每个测试用独立缓存文件，避免污染真实模拟盘
_cache_dir = tempfile.mkdtemp(prefix="paper_test_")
os.environ["STOCKAI_CACHE_DIR"] = _cache_dir

from core.portfolio import paper  # noqa: E402


class TestPaperOrder(unittest.TestCase):
    def setUp(self):
        paper.reset()

    def test_market_buy_whole_lot_and_fees(self):
        r = paper.place_order("600519", "CN", "买入", "market", 100, 1500.0)
        self.assertEqual(r["shares"], 100)
        self.assertEqual(r["price"], round(1500 * 1.001, 4))  # 滑点向上
        s = paper.summary()
        # 现金扣：1500*100*1.001 + 佣金(≥5) + 印花税0 + 滑点
        spent = 100 * r["price"]
        self.assertLess(s["cash"], paper.INIT_CAPITAL - spent + 1)
        self.assertGreaterEqual(paper.positions()[0]["shares"], 100)

    def test_market_sell_fees_include_stamp_tax(self):
        paper.place_order("AAPL", "US", "买入", "market", 10, 200.0)
        r = paper.place_order("AAPL", "US", "卖出", "market", 10, 210.0)
        self.assertEqual(r["shares"], 10)
        self.assertAlmostEqual(r["price"], round(210 * 0.999, 4))  # 滑点向下
        self.assertIn("含费", r["note"])

    def test_limit_not_triggered(self):
        r = paper.place_order("600519", "CN", "买入", "limit", 100, 1500.0,
                              limit_price=1400.0)
        self.assertEqual(r["shares"], 0)
        self.assertIn("限价未触发", r["note"])

    def test_limit_triggered(self):
        r = paper.place_order("600519", "CN", "买入", "limit", 100, 1500.0,
                              limit_price=1550.0)
        self.assertEqual(r["shares"], 100)

    def test_stop_not_triggered(self):
        # 卖出止损：现价 1500 未跌破触发价 1400 → 挂起
        r = paper.place_order("600519", "CN", "卖出", "stop", 100, 1500.0,
                              stop_price=1400.0)
        self.assertEqual(r["shares"], 0)
        self.assertIn("止损未触发", r["note"])

    def test_stop_triggered_sell(self):
        # 卖出止损：现价 1450 已跌破触发价 1500 → 触发离场
        paper.place_order("600519", "CN", "买入", "market", 200, 1500.0)
        r = paper.place_order("600519", "CN", "卖出", "stop", 100, 1450.0,
                              stop_price=1500.0)
        self.assertEqual(r["shares"], 100)

    def test_stop_triggered_buy(self):
        # 买入突破：现价 1500 已突破触发价 1400 → 触发买入
        r = paper.place_order("600519", "CN", "买入", "stop", 100, 1500.0,
                              stop_price=1400.0)
        self.assertEqual(r["shares"], 100)

    def test_cn_lot_rounding(self):
        r = paper.place_order("600519", "CN", "买入", "market", 250, 100.0)
        self.assertEqual(r["shares"], 200)  # 250 → 200（整手）

    def test_sell_no_position(self):
        r = paper.place_order("000001", "CN", "卖出", "market", 100, 10.0)
        self.assertEqual(r["shares"], 0)
        self.assertIn("无持仓", r["note"])

    def test_partial_sell(self):
        paper.place_order("600519", "CN", "买入", "market", 300, 100.0)
        r = paper.place_order("600519", "CN", "卖出", "market", 100, 110.0)
        self.assertEqual(r["shares"], 100)
        self.assertEqual(paper.positions()[0]["shares"], 200)

    def test_insufficient_cash(self):
        r = paper.place_order("600519", "CN", "买入", "market", 100000, 999999.0)
        self.assertEqual(r["shares"], 0)
        self.assertIn("现金不足", r["note"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
