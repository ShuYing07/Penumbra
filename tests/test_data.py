# -*- coding: utf-8 -*-
"""测试数据获取"""
import sys, time
sys.path.insert(0, '.')
from core.data.akshare_source import fetch_daily_cn

t0 = time.time()
try:
    df = fetch_daily_cn('SH600519')
    last_date = df.index[-1]
    last_close = df['close'].iloc[-1]
    print(f"OK: {len(df)} rows, last={last_date}, close={last_close}, {time.time()-t0:.1f}s")
except Exception as e:
    print(f"FAIL: {type(e).__name__}: {e}, {time.time()-t0:.1f}s")
