# -*- coding: utf-8 -*-
"""测试Tushare接口权限。"""
import requests, json

TOKEN = "1798f45550308dfcf856be3f1cd9286bda7f2474bdf6126d8b263ff6"

def call(api, **params):
    r = requests.post("https://api.tushare.pro", json={
        "api_name": api, "token": TOKEN,
        "params": params, "fields": ""
    }, timeout=30)
    return r.json()

for api in ["stock_basic", "trade_cal", "daily", "hk_basic", "us_basic", "index_basic"]:
    d = call(api, list_status="L")
    code = d.get("code")
    msg = d.get("msg", "")
    print(f"{api}: code={code} msg={msg[:100]}")
    if code == 0:
        fields = d["data"]["fields"][:5]
        n = len(d["data"]["items"])
        print(f"  -> fields={fields}... items={n}")
