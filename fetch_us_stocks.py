# -*- coding: utf-8 -*-
import json
import time
import requests

s = requests.Session()
s.trust_env = False

with open("D:/StockAIPredictor/data/all_stocks.json", "r", encoding="utf-8") as f:
    stocks = json.load(f)
existing = set(s["code"] for s in stocks)

# 东方财富美股接口 m:105 纳斯达克, m:106 纽交所
boards = [
    ("m:105", "纳斯达克"),
    ("m:106", "纽交所"),
]
us = []
for fs, board in boards:
    page = 1
    while True:
        try:
            r = s.get(
                "https://82.push2.eastmoney.com/api/qt/clist/get",
                params={
                    "pn": page, "pz": 100, "po": 1, "np": 1,
                    "fltt": 2, "invt": 2, "fid": "f12",
                    "fs": fs, "fields": "f12,f14",
                },
                timeout=15,
            )
            data = r.json().get("data", {})
            items = data.get("diff", [])
            if not items:
                break
            for item in items:
                code = str(item.get("f12", "")).strip().upper()
                name = str(item.get("f14", "")).strip()
                if not code or code in existing:
                    continue
                us.append({"code": code, "name": name, "market": "US", "board": board, "ticker": code})
            total = data.get("total", 0)
            print(f"{board} page{page}: {len(us)}/{total}")
            if page * 100 >= total:
                break
            page += 1
            time.sleep(0.2)
        except Exception as e:
            print(f"{board} page{page} error: {e}")
            break

print(f"拉到{len(us)}只美股")
stocks.extend(us)
with open("D:/StockAIPredictor/data/all_stocks.json", "w", encoding="utf-8") as f:
    json.dump(stocks, f, ensure_ascii=False)
print(f"总共{len(stocks)}只")
