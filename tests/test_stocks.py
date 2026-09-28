# -*- coding: utf-8 -*-
import json, os, requests
os.environ.pop("HTTP_PROXY", None); os.environ.pop("HTTPS_PROXY", None)
s = requests.Session(); s.trust_env = False
stocks = json.load(open("D:/StockAIPredictor/data/all_stocks.json", encoding="utf-8"))

boards = {}
for st in stocks:
    boards.setdefault(st["board"], []).append(st)
test = []
for b, sl in boards.items():
    for x in sl[:3]:
        test.append(x)

print(f"测试{len(test)}只...")
ok = fail = 0
for x in test:
    code = x["code"]
    prefix = x.get("secid_prefix", "1")
    secid = f"{prefix}.{code}"
    try:
        r = s.get("https://push2.eastmoney.com/api/qt/stock/get",
                  params={"secid": secid, "fields": "f43,f57,f58"}, timeout=8)
        d = r.json().get("data")
        if d and isinstance(d, dict) and d.get("f43") not in (None, "-"):
            ok += 1
            print(f"  OK  {code} {x['name']}")
        else:
            fail += 1
            print(f"  FAIL {code} {x['name']}")
    except Exception as e:
        fail += 1
        print(f"  ERR  {code} {x['name']}: {e}")
print(f"\n成功: {ok}, 失败: {fail}")
