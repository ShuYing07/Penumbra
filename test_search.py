# -*- coding: utf-8 -*-
from core.search.stock_index import get_pinyin_abbr, search_stocks
print("贵州茅台:", get_pinyin_abbr("贵州茅台"))
print("平安银行:", get_pinyin_abbr("平安银行"))
print("宁德时代:", get_pinyin_abbr("宁德时代"))
print("比亚迪:", get_pinyin_abbr("比亚迪"))

stocks = [
    {"code": "600519", "name": "贵州茅台", "pinyin": get_pinyin_abbr("贵州茅台"), "market": "SH", "ticker": "SH600519"},
    {"code": "000001", "name": "平安银行", "pinyin": get_pinyin_abbr("平安银行"), "market": "SZ", "ticker": "SZ000001"},
    {"code": "300750", "name": "宁德时代", "pinyin": get_pinyin_abbr("宁德时代"), "market": "SZ", "ticker": "SZ300750"},
    {"code": "002594", "name": "比亚迪", "pinyin": get_pinyin_abbr("比亚迪"), "market": "SZ", "ticker": "SZ002594"},
]
for q in ["gzmt", "payh", "ndsd", "byd", "600519", "茅台", "平安", "宁德", "比亚"]:
    r = search_stocks(q, stocks)
    name = r[0]["name"] if r else "无"
    print("搜", q, ":", name)
