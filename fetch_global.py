# -*- coding: utf-8 -*-
"""拉全球股票（A股+美股+港股+日股+英股等）。"""
import json
import time
import requests

s = requests.Session()
s.trust_env = False

with open("D:/StockAIPredictor/data/all_stocks.json", "r", encoding="utf-8") as f:
    stocks = json.load(f)
existing = set(x["code"] for x in stocks)
print(f"已有{len(stocks)}只")

# 东方财富市场代码
markets = [
    ("m:128 t:11", "港股主板", "HK"),
    ("m:128 t:13", "港股创业板", "HK"),
    ("m:136 t:1", "日本", "JP"),
    ("m:137 t:1", "英国", "UK"),
    ("m:139 t:1", "德国", "DE"),
    ("m:140 t:1", "印度", "IN"),
    ("m:141 t:1", "加拿大", "CA"),
    ("m:142 t:1", "澳大利亚", "AU"),
    ("m:143 t:1", "新加坡", "SG"),
    ("m:144 t:1", "韩国", "KR"),
]

for fs, board, mkt in markets:
    added = 0
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
            if not data:
                break
            items = data.get("diff", [])
            if not items:
                break
            for item in items:
                code = str(item.get("f12", "")).strip().upper()
                name = str(item.get("f14", "")).strip()
                if not code or not name or code in existing:
                    continue
                existing.add(code)
                stocks.append({"code": code, "name": name, "market": mkt, "board": board, "ticker": code})
                added += 1
            total = data.get("total", 0)
            if page * 100 >= total:
                break
            page += 1
            time.sleep(0.15)
        except Exception as e:
            print(f"{board} p{page} err: {e}")
            break
    print(f"{board}: +{added}")

with open("D:/StockAIPredictor/data/all_stocks.json", "w", encoding="utf-8") as f:
    json.dump(stocks, f, ensure_ascii=False)
print(f"总共{len(stocks)}只")
