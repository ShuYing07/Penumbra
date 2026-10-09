# -*- coding: utf-8 -*-
"""app/ui/eval_tab.py 分析质量总览面板测试（offscreen）。

验证：三个子页存在、四维雷达图取到 4 维数据、匹配结论可读、
置信度色板不占用涨跌红绿、{red team 护栏得分卡行数与状态}，以及
空输入时不崩。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("STOCKAI_MOCK", "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PyQt6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

from app.ui.eval_tab import EvalTab, _RadarChart, _TrendChart  # noqa: E402

PASS = 0


def ok(name: str):
    global PASS
    PASS += 1
    print(f"[ok] {name}")


def test_instantiates_with_three_pages():
    tab = EvalTab()
    assert tab is not None
    assert tab.sub.count() == 3, tab.sub.count()
    texts = [tab.sub.tabText(i) for i in range(tab.sub.count())]
    assert "八维评测" in texts and "四维质量" in texts and "可信度与护栏" in texts
    ok(f"分析质量三子页：{texts}")


def test_eight_dim_bars_present():
    tab = EvalTab()
    assert len(tab.bars) == 8
    ok("八维评分条 8 条")


def test_radar_draws_four_dims():
    tab = EvalTab()
    tab.q_text.setPlainText(
        "应急资金应以流动性优先，建议配置货币基金/短债，该类别波动极低、"
        "随时可取；若市场利率上行存在净值波动风险；不构成投资建议，风险自担。")
    idx = next(i for i in range(tab.profile.count())
               if tab.profile.itemData(i) == "emergency")
    tab.profile.setCurrentIndex(idx)
    tab._run_quality()
    assert tab.radar._items, "雷达图应有数据"
    assert len(tab.radar._items) == 4
    names = {n for n, _v in tab.radar._items}
    assert names == {"正确性", "适配性", "鲁棒性", "合规性"}, names
    assert "总分" in tab.q_result.text()
    assert "匹配结论" in tab.q_match.text()
    ok(f"四维雷达：{tab.q_result.text()}")


def test_quality_detects_mismatch():
    tab = EvalTab()
    tab.q_text.setPlainText("建议买入股票，目标价 2000 元，预计翻倍。")
    idx = next(i for i in range(tab.profile.count())
               if tab.profile.itemData(i) == "emergency")
    tab.profile.setCurrentIndex(idx)
    tab._run_quality()
    assert "不匹配" in tab.q_match.text(), tab.q_match.text()
    ok("资金-资产不匹配被识别")


def test_confidence_uses_neutral_color():
    tab = EvalTab()
    tab.ev_count.setValue(5)
    tab.ev_days.setValue(3)
    tab.sample.setValue(500)
    tab.disagree.setValue(10)
    tab.decay.setValue(5)
    tab._run_confidence()
    assert "置信度" in tab.conf_lbl.text()
    color = tab.conf_lbl.styleSheet()
    assert "#00C853" not in color and "#FF1744" not in color, color
    assert tab.conf_bar.value() > 0
    ok(f"置信度面板（中性色）：{tab.conf_lbl.text()}")


def test_confidence_no_evidence_blocks():
    tab = EvalTab()
    tab.ev_count.setValue(0)
    tab.sample.setValue(5)
    tab._run_confidence()
    assert "不足" in tab.conf_lbl.text(), tab.conf_lbl.text()
    ok("零证据 → 置信度不足并提示不得单独展示")


def test_confidence_caveats_rendered():
    tab = EvalTab()
    tab.ev_count.setValue(1)
    tab.ev_days.setValue(200)
    tab.disagree.setValue(80)
    tab.unresolved.setValue(3)
    tab._run_confidence()
    body = tab.caveats.toPlainText()
    assert "限制条件" in body
    assert "七因子" in body
    ok("限制条件与因子贡献渲染正常")


def test_redteam_scorecard_fills():
    tab = EvalTab()
    tab._run_redteam()
    assert tab.red_table.rowCount() == 10, tab.red_table.rowCount()
    header = tab.red_table.horizontalHeaderItem(0).text()
    assert header == "攻击技术族"
    statuses = {tab.red_table.item(i, 4).text() for i in range(10)}
    assert "稳固" in statuses or "待加固" in statuses, statuses
    ok(f"红队护栏得分卡 {tab.red_table.rowCount()} 行：{sorted(statuses)}")


def test_empty_input_no_crash():
    tab = EvalTab()
    tab.q_text.setPlainText("")
    tab._run_quality()
    tab.text.setPlainText("")
    tab.ref.setText("{bad json")
    tab._run()
    assert "解析失败" in tab.total_lbl.text(), tab.total_lbl.text()
    ok("空输入 / 坏 JSON 不崩溃")


def test_radar_widget_standalone():
    r = _RadarChart()
    r.set_data([("A", 0.5), ("B", 0.6), ("C", 0.7)])
    r.resize(200, 200)
    r.render(r.grab())          # 触发 paintEvent（少于 3 维走占位分支也不崩）
    r.set_data([("A", -1.0), ("B", 5.0), ("C", 0.5)])
    r.render(r.grab())          # 越界值被夹紧
    ok("雷达图控件：少于三维占位 + 越界值夹紧")


def test_trend_widget_standalone():
    t = _TrendChart()
    t.resize(200, 120)
    t.render(t.grab())          # 空数据占位
    t.set_data([0.2, 0.5, 0.9])
    t.render(t.grab())
    assert len(t._points) == 3
    ok("趋势图控件：空数据占位 + 三点折线")


if __name__ == "__main__":
    test_instantiates_with_three_pages()
    test_eight_dim_bars_present()
    test_radar_draws_four_dims()
    test_quality_detects_mismatch()
    test_confidence_uses_neutral_color()
    test_confidence_no_evidence_blocks()
    test_confidence_caveats_rendered()
    test_redteam_scorecard_fills()
    test_empty_input_no_crash()
    test_radar_widget_standalone()
    test_trend_widget_standalone()
    print(f"\nALL PASS ({PASS})")
