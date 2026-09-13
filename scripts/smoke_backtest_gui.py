# -*- coding: utf-8 -*-
"""回测页 offscreen 冒烟：构建主窗口→6 标签→策略切换→同步跑一次真实回测。"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PyQt6.QtWidgets import QApplication  # noqa: E402

from app.ui.main_window import MainWindow  # noqa: E402
from core.data.service import get_daily, market_of  # noqa: E402
from core.quant.backtest import BacktestConfig, run_backtest  # noqa: E402

app = QApplication([])
win = MainWindow()
tabs = win.centralWidget()
assert tabs.count() == 6, f"标签数 {tabs.count()} != 6"
labels = [tabs.tabText(i) for i in range(tabs.count())]
assert labels == ["分析", "K线图", "模拟盘", "回测", "学习库", "决策记录"], labels
print("PASS 主窗口 6 标签：", labels)

bt = win.backtest_tab
# 策略参数框切换
for idx in range(bt.cb_strategy.count()):
    bt.cb_strategy.setCurrentIndex(idx)
    key = bt.cb_strategy.currentData()
    for k, box in bt._param_boxes.items():
        assert (not box.isHidden()) == (k == key), f"{k} 可见性错误（当前策略 {key}）"
print("PASS 策略切换参数框显示正确：", [bt.cb_strategy.itemText(i) for i in range(bt.cb_strategy.count())])

# 同步跑一次真实回测（缓存数据），直接调核心，验证 UI 数据路径
bt.cb_strategy.setCurrentIndex(0)  # rsi_reversion
df, status = get_daily("SH600519")
market = market_of("SH600519")
cfg = BacktestConfig(ticker="SH600519", market=market, start="2023-01-01")
res = run_backtest(df, market, "rsi_reversion", {}, cfg)
m = res.metrics
assert m["final_equity"] > 0
assert -100 <= m["max_drawdown_pct"] <= 0
assert 0 <= m["win_rate_pct"] <= 100
assert len(res.equity) > 30
print(f"PASS 真实回测（2023起）：总收益 {m['total_return_pct']}% 回撤 {m['max_drawdown_pct']}% "
      f"胜率 {m['win_rate_pct']}% 成交 {m['trade_count']} 笔")

# 喂给 UI 渲染路径（不经过线程）
bt._on_done(res)
assert bt.metric_table.item(0, 1).text() != "—"
assert bt.trade_table.rowCount() == len(res.trades)
print("PASS UI 指标表/成交表渲染")

print("\n回测 GUI 冒烟全部通过")
