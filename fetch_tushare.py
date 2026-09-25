# -*- coding: utf-8 -*-
"""用Tushare拉全量A股/港股/美股列表。"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

TOKEN = "1798f45550308dfcf856be3f1cd9286bda7f2474bdf6126d8b263ff6"

def call(api_name, **params):
    import requests
    r = requests.post("https://api.tushare.pro", json={
        "api_name": api_name, "token": TOKEN,
        "params": params, "fields": "",
    }, timeout=30, proxies={"http": None, "https": None})
    d = r.json()
    if d.get("code") != 0:
        print(f"FAIL {api_name}: {d.get('msg')}")
        return []
    fields = d["data"]["fields"]
    return [dict(zip(fields, row)) for row in d["data"]["items"]]

print("=== A股 stock_basic ===")
a_sh = call("stock_basic", exchange="", list_status="L",
            fields="ts_code,symbol,name,area,industry,market,list_date")
print(f"A股: {len(a_sh)}")

# 分类
boards = {
    "沪市主板": ["主板"],
    "科创板": ["科创板"],
    "深市主板": ["主板"],
    "创业板": ["创业板"],
    "北交所": ["北交所"],
}

stocks = []
for s in a_sh:
    mkt = s.get("market", "")
    if mkt == "主板":
        board = "沪市主板" if s["symbol"].startswith("6") else "深市主板"
    elif mkt == "科创板":
        board = "科创板"
    elif mkt == "创业板":
        board = "创业板"
    elif mkt == "北交所":
        board = "北交所"
    else:
        board = mkt or "其他"
    stocks.append({
        "code": s["symbol"],
        "name": s["name"],
        "market": "A股",
        "board": board,
        "ticker": s["symbol"],
        "secid_prefix": "1" if s["symbol"].startswith(("6","9")) else "0",
        "industry": s.get("industry", ""),
        "list_date": s.get("list_date", ""),
    })

print(f"A股分类: {len(stocks)}")

# 港股
print("=== 港股 hk_basic ===")
try:
    hk = call("hk_basic", list_status="L")
    print(f"港股: {len(hk)}")
    for s in hk:
        stocks.append({
            "code": s.get("ts_code",""),
            "name": s.get("name",""),
            "market": "港股",
            "board": "港股主板",
            "ticker": s.get("symbol",""),
            "secid_prefix": "116",
            "industry": s.get("industry",""),
            "list_date": s.get("list_date",""),
        })
except Exception as e:
    print(f"港股失败: {e}")

# 美股
print("=== 美股 us_basic ===")
try:
    us = call("us_basic", list_status="L")
    print(f"美股: {len(us)}")
    for s in us:
        # 纳斯达克前缀105，纽交所106
        exch = s.get("exchange", "")
        prefix = "105" if exch == "NASDAQ" else "106"
        stocks.append({
            "code": s.get("ts_code",""),
            "name": s.get("name",""),
            "market": "美股",
            "board": "纳斯达克" if exch == "NASDAQ" else "纽交所",
            "ticker": s.get("symbol",""),
            "secid_prefix": prefix,
            "industry": s.get("industry",""),
            "list_date": s.get("list_date",""),
        })
except Exception as e:
    print(f"美股失败: {e}")

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "all_stocks.json")
with open(out, "w", encoding="utf-8") as f:
    json.dump(stocks, f, ensure_ascii=False, indent=1)
print(f"\n总股票数: {len(stocks)}")
print(f"保存到: {out}")