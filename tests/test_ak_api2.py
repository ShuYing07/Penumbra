# -*- coding: utf-8 -*-
"""测试公告接口参数"""
import sys
sys.path.insert(0, '.')
from core.config import domestic_network
import akshare as ak

# 测试公告接口不同参数
with domestic_network():
    try:
        # 可能需要symbol格式不同
        df = ak.stock_notice_report(symbol="全部")
        print("symbol=全部:", df.columns.tolist() if df is not None else "None")
        print(df.head(2).to_string() if df is not None and len(df)>0 else "")
    except Exception as e:
        print(f"symbol=全部 FAIL: {e}")
    
    # 研报接口
    try:
        df2 = ak.stock_research_report_em(symbol="600519")
        print("\n研报:", df2.columns.tolist() if df2 is not None else "None")
        print(df2.head(2).to_string() if df2 is not None and len(df2)>0 else "")
    except Exception as e:
        print(f"\n研报 FAIL: {e}")
