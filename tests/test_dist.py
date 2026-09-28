# -*- coding: utf-8 -*-
import sys, os
sys.path.insert(0, r"D:\StockAIPredictor")
os.chdir(r"D:\StockAIPredictor")

try:
    import akshare as ak
    print(f"akshare版本: {ak.__version__}")
    print("正在获取贵州茅台数据...")
    df = ak.stock_zh_a_daily(symbol="sh600519", adjust="qfq")
    print(f"新浪接口成功: {len(df)}行")
    print(f"最新收盘: {df['close'].iloc[-1]}")
except Exception as e:
    import traceback
    print(f"错误: {e}")
    traceback.print_exc()
