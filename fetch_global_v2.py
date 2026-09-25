# -*- coding: utf-8 -*-
"""从东方财富拉美股+港股，走代理，带重试。"""
import requests, json, time, os

PROXY = {"http": "http://127.0.0.1:7897", "https": "http://127.0.0.1:7897"}
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

def fetch_list(secid_prefix, fs, board, market, max_pages=100):
    stocks = []
    for page in range(1, max_pages + 1):
        url = "https://82.push2.eastmoney.com/api/qt/clist/get"
        params = {
            "pn": page, "pz": 200, "po": 1, "np": 1,
            "fltt": 2, "invt": 2, "fid": "f12",
            "fs": fs, "fields": "f12,f14",
        }
        for attempt in range(5):
            try:
                s = requests.Session()
                s.proxies = PROXY
                s.headers.update(HEADERS)
                r = s.get(url, params=params, timeout=20)
                data = r.json().get("data", {})
                items = data.get("diff", [])
                if not items:
                    return stocks
                for it in items:
                    code = str(it.get("f12", "")).strip()
                    name = str(it.get("f14", "")).strip()
                    if not code or not name:
                        continue
                    stocks.append({
                        "code": code, "name": name,
                        "market": market, "board": board,
                        "ticker": code, "secid_prefix": str(secid_prefix),
                    })
                total = data.get("total", 0)
                print(f"  {board} p{page}: {len(stocks)}/{total}")
                if page * 200 >= total:
                    return stocks
                time.sleep(0.3)
                break
            except Exception as e:
                if attempt == 4:
                    print(f"  {board} p{page} FAIL: {e}")
                    return stocks
                time.sleep(2)
    return stocks

print("=== 美股 ===")
us = []
for secid, board in [(105, "纳斯达克"), (106, "纽交所")]:
    fs = f"m:{secid}+t:6,m:{secid}+t:80,m:{secid}+t:81,m:{secid}+t:10"
    us += fetch_list(secid, fs, board, "美股")

print("=== 港股 ===")
hk = fetch_list(116, "m:128+t:3,m:128+t:4,m:128+t:1,m:128+t:2", "港股主板", "港股")

# 读A股
with open("data/a_stocks.json", encoding="utf-8") as f:
    a_stocks = json.load(f)

# 合并
all_stocks = a_stocks + us + hk
# 去重
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
print(f"美股: {len(us)}")
print(f"港股: {len(hk)}")
print(f"总计: {len(uniq)}")
