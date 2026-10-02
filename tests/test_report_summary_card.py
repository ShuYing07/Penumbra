# -*- coding: utf-8 -*-
"""财报摘要卡片测试：确定性 mock 数据 → 卡片组装 / 多期对比 / 同行雷达数据。"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("STOCKAI_MOCK", "1")

import core.report_summary_card as rsc


def _fake_reports(n=4):
    out = []
    for i in range(n):
        out.append({
            "report_date": f"2025-Q{i+1}",
            "revenue": 100 + i * 10, "net_profit": 20 + i * 2,
            "gross_margin": 0.45, "roe": 0.18, "eps": 2.0 + i * 0.2,
            "debt_ratio": 0.4, "period": f"2025Q{i+1}",
        })
    return out


class TestReportSummaryCard(unittest.TestCase):
    @mock.patch.object(rsc, "get_financial_reports", side_effect=lambda t, periods=4: _fake_reports())
    @mock.patch.object(rsc, "extract_key_info", return_value={
        "highlights": ["营收稳步增长"], "risks": ["行业竞争加剧"]})
    def test_build_card(self, _ek, _gf):
        card = rsc.build_summary_card("600519")
        self.assertEqual(card.ticker, "600519")
        self.assertGreater(card.revenue, 0)
        self.assertGreater(card.roe, 0)
        self.assertEqual(len(card.key_points), 1)
        self.assertEqual(card.risks[0], "行业竞争加剧")
        self.assertIn("source", card.to_dict())
        self.assertIn("fetched_at", card.to_dict())

    def test_multi_period_compare(self):
        rows = rsc.multi_period_compare(_fake_reports())
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[0]["period"], "2025-Q1")
        self.assertGreater(rows[3]["revenue"], rows[0]["revenue"])  # 递增
        for k in ("gross_margin", "roe", "eps"):
            self.assertIn(k, rows[0])

    def test_peer_compare(self):
        with mock.patch.object(rsc, "get_financial_reports",
                               side_effect=lambda t, periods=1: _fake_reports(1)):
            out = rsc.peer_compare("600519", ["000858", "000568"])
            self.assertEqual(out["ticker"], "600519")
            self.assertEqual(len(out["peers"]), 2)
            self.assertIn("roe", out["peers"][0])
            self.assertIn("gross_margin", out["peers"][0])

    def test_peer_compare_degrades_on_failure(self):
        def _boom(ticker, periods=1):
            raise RuntimeError("数据源不可用")
        with mock.patch.object(rsc, "get_financial_reports", side_effect=_boom):
            out = rsc.peer_compare("600519", ["000858"])
            self.assertIn("error", out["peers"][0])

    def test_card_dict_roundtrip(self):
        card = rsc.ReportSummaryCard(ticker="AAPL", revenue=1.0, key_points=["a"],
                                     risks=["b"], dcf={"value": 100})
        d = card.to_dict()
        self.assertEqual(d["ticker"], "AAPL")
        self.assertEqual(d["dcf"]["value"], 100)


if __name__ == "__main__":
    unittest.main(verbosity=2)
