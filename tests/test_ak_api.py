# -*- coding: utf-8 -*-
"""检查AKShare新闻接口的正确用法"""
import sys
sys.path.insert(0, '.')
from core.config import domestic_network
import akshare as ak

# 测试个股新闻
print("=== stock_news_em ===")
with domestic_network():
    df = ak.stock_news_em(symbol="600519")
print(df.columns.tolist() if df is not None else "None")
print(df.head(2).to_string() if df is not None and len(df)>0 else "")

# 测试公告接口
print("\n=== 公告接口候选 ===")
for func_name in ['stock_notice_report', 'stock_notice_em', 'stock_announcement_em']:
    if hasattr(ak, func_name):
        print(f"  {func_name}: 存在")
    else:
        print(f"  {func_name}: 不存在")
