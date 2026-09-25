# -*- coding: utf-8 -*-
"""用yfinance拉美股+港股列表。"""
import json, time
import yfinance as yf

# 美股：用yfinance搜索
print("=== 美股 ===")
# yfinance没有直接的"全市场列表"接口，用已知热门列表
# 实际上用akshare的stock_us_spot_em
import akshare as ak

us_stocks = []
try:
    df = ak.stock_us_spot_em()
    print(f"美股总数: {len(df)}")
    print(df.columns.tolist())
    for _, row in df.iterrows():
        code = str(row.get("代码", "")).strip()
        name = str(row.get("名称", "")).strip()
        if not code:
            continue
        us_stocks.append({
            "code": code, "name": name,
            "market": "美股", "board": "美股",
            "ticker": code, "secid_prefix": "105",
        })
except Exception as e:
    print(f"美股失败: {e}")

print("=== 港股 ===")
hk_stocks = []
try:
    df = ak.stock_hk_spot_em()
    print(f"港股总数: {len(df)}")
    for _, row in df.iterrows():
        code = str(row.get("代码", "")).strip()
        name = str(row.get("名称", "")).strip()
        if not code:
            continue
        hk_stocks.append({
            "code": code, "name": name,
            "market": "港股", "board": "港股主板",
            "ticker": code, "secid_prefix": "116",
        })
except Exception as e:
    print(f"港股失败: {e}")

# 读A股
with open("data/a_stocks.json", encoding="utf-8") as f:
    a_stocks = json.load(f)

all_stocks = a_stocks + us_stocks + hk_stocks
seen = set()
uniq = []
for s in all_stocks:
    key = s["code"]
    if key not in seen:
        seen.add(key)
        uniq.append(s)

with open("data/all_stocks.json", "w", encoding="utf-8") as f:
    json.dump(uniq, f, ensure_ascii=False)

print(f"\n=== 总计 ===")
print(f"A股: {len(a_stocks)}")
print(f"美股: {len(us_stocks)}")
print(f"港股: {len(hk_stocks)}")
print(f"总计: {len(uniq)}")
