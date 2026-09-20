# -*- coding: utf-8 -*-
"""测试贵州茅台数据获取"""
import sys
sys.path.insert(0, '.')

from core.data.service import get_daily, normalize_ticker

print("=== 测试贵州茅台 ===")
t = normalize_ticker('600519')
print(f'normalize: 600519 -> {t}')

try:
    df, status = get_daily(t)
    print(f'数据状态: {status}')
    print(f'数据行数: {len(df)}')
    print(f'列名: {list(df.columns)}')
    if len(df) > 0:
        print(f'最新日期: {df.index[-1]}')
        last = df.iloc[-1]
        print(f'最新收盘: {last["close"]}')
        print(f'最新成交量: {last["volume"]}')
except Exception as e:
    import traceback
    traceback.print_exc()
