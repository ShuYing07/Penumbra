# -*- coding: utf-8 -*-
"""测试自选股实时数据获取"""
import sys
sys.path.insert(0, '.')
from core.data.service import normalize_ticker, get_realtime, market_of

for code in ['600519', '000001', '300750', '601318']:
    t = normalize_ticker(code)
    m = market_of(t)
    try:
        r = get_realtime(t)
        print(f"{code} -> {t} [{m}]  现价={r.get('price')}  涨跌={r.get('chg_pct')}%  名称={r.get('name')}")
    except Exception as e:
        print(f"{code} -> {t} [{m}]  FAIL: {e}")
