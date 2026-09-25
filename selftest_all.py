# -*- coding: utf-8 -*-
"""全面自测所有功能。"""
import sys, os
os.environ["QT_QPA_PLATFORM"] = "offscreen"

print("=" * 50)
print("疏影·知微 全面自测")
print("=" * 50)

# 1. 核心模块
print("\n[1] 核心模块导入")
mods = [
    "rigor", "nl_intent", "mcp_server", "auto_train", "auto_scheduler",
    "news_pipeline", "local_rag", "knowledge_graph",
    "risk_control_agent", "wyckoff_analyzer", "kronos_predictor",
    "portfolio_optimizer",
    "core.search.stock_index", "core.quant.dcf_model", "core.quant.backtest",
]
for m in mods:
    try:
        __import__(m)
        print(f"  OK  {m}")
    except Exception as e:
        print(f"  ERR {m}: {e}")

# 2. 行情数据
print("\n[2] 行情数据")
from core.data.service import get_daily
for code, name in [("SH600519", "贵州茅台"), ("SZ000858", "五粮液"), ("AAPL", "苹果")]:
    try:
        bars, _ = get_daily(code)
        if bars is not None and len(bars) > 0:
            print(f"  OK  {name}: {len(bars)}条, 最新{bars.iloc[-1]['close']:.2f}")
        else:
            print(f"  ERR {name}: 无数据")
    except Exception as e:
        print(f"  ERR {name}: {e}")

# 3. 股票搜索
print("\n[3] 股票搜索")
from core.search.stock_index import search_stocks, load_index
idx = load_index()
print(f"  索引: {len(idx)}条")
for q in ["茅台", "gzmt", "aapl", "腾讯"]:
    r = search_stocks(q, idx, limit=1)
    if r:
        print(f"  '{q}' -> {r[0]['code']} {r[0]['name']}")
    else:
        print(f"  '{q}' -> 无结果")

# 4. NL解析
print("\n[4] 自然语言解析")
from nl_intent import parse_intent
for q in ["分析茅台", "看看600519的K线", "腾讯新闻"]:
    r = parse_intent(q)
    print(f"  '{q}' -> {r.action}/{r.ticker}")

# 5. 组合优化
print("\n[5] 组合优化")
import numpy as np, pandas as pd
rets = pd.DataFrame({"A": np.random.normal(0, 0.02, 100), "B": np.random.normal(0, 0.02, 100)})
from portfolio_optimizer import equal_weight, min_variance, risk_parity
print(f"  等权重: {equal_weight(rets)}")
print(f"  最小方差: {min_variance(rets)}")

# 6. 统计检验
print("\n[6] 统计检验")
from rigor import permutation_test, check_sample_size
r = permutation_test([1,2,3,4,5], [2,3,4,5,6], 100)
print(f"  p值: {r['p_value']}")

# 7. UI
print("\n[7] UI启动")
from PyQt6.QtWidgets import QApplication
from app.ui.ui_theme import apply_theme
app = QApplication([])
apply_theme(app)
from app.ui.main_window import MainWindow
w = MainWindow()
print(f"  tabs: {w.tabs.count()}, nav: {len(w.nav_buttons)}")
print(f"  scheduler: {'OK' if hasattr(w, '_scheduler') else '未加载'}")

# 8. 数据文件
print("\n[8] 数据文件")
import json
with open("data/all_stocks.json", encoding="utf-8") as f:
    stocks = json.load(f)
from collections import Counter
print(f"  股票总数: {len(stocks)}")
print(f"  市场: {dict(Counter(s['market'] for s in stocks))}")

print("\n" + "=" * 50)
print("自测完成")

