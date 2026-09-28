# -*- coding: utf-8 -*-
import sys, os
sys.path.insert(0, '.')
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

from core.data.service import get_daily
df, status = get_daily('SH600519')
print(f'状态: {status}')
print(f'行数: {len(df)}')
last = df.iloc[-1]
print(f'最新收盘: {last["close"]}')
print(f'最新日期: {df.index[-1]}')
