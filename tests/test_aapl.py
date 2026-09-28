import os
import sys
sys.path.insert(0, r"D:\StockAIPredictor")
from core.data.service import get_daily
bars, _ = get_daily("AAPL")
if bars is not None and len(bars) > 0:
    print(f"AAPL: {len(bars)}条, 最新{bars.iloc[-1]['close']:.2f}")
else:
    print("AAPL: 无数据")
