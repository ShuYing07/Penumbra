# -*- coding: utf-8 -*-
"""补齐 all_stocks.json 中缺失的关键标的与指数。

用途：默认自选股（贵州茅台/苹果/沪深300/宁德时代/腾讯控股）与
命令面板搜索依赖本地股票索引；早期生成的数据缺少 AAPL、SH000300、
HK00700 及主要指数，导致真实环境"无法识别标的"。

修复方式：幂等追加缺失条目（含 alias 拼音/英文别名），保留原有序。
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(ROOT, "data", "all_stocks.json")

# (匹配键, 补充条目)
EXTRA = [
    ("code", "000300", {
        "code": "000300", "name": "沪深300", "market": "A股",
        "board": "指数", "ticker": "SH000300", "secid_prefix": "1",
        "alias": ["hs300", "csi300"],
    }),
    ("code", "399006", {
        "code": "399006", "name": "创业板指", "market": "A股",
        "board": "指数", "ticker": "SZ399006", "secid_prefix": "0",
        "alias": ["cyb"],
    }),
    ("code", "000001", {
        "code": "000001", "name": "上证指数", "market": "A股",
        "board": "指数", "ticker": "SH000001", "secid_prefix": "1",
        "alias": ["szzs", "shangzheng"],
    }),
    ("code", "399001", {
        "code": "399001", "name": "深证成指", "market": "A股",
        "board": "指数", "ticker": "SZ399001", "secid_prefix": "0",
        "alias": ["szcz", "shenzheng"],
    }),
    ("ticker", "AAPL", {
        "code": "AAPL", "name": "苹果", "market": "美股",
        "board": "纳斯达克", "ticker": "AAPL", "secid_prefix": "105",
        "alias": ["apple", "apl"],
    }),
    ("ticker", "HK00700", {
        "code": "0700.HK", "name": "腾讯控股", "market": "港股",
        "board": "主板", "ticker": "HK00700", "secid_prefix": "116",
        "alias": ["tencent", "tengxun", "0700"],
    }),
]


def main() -> None:
    with open(PATH, encoding="utf-8") as f:
        data = json.load(f)

    existing = set()
    for s in data:
        existing.add(str(s.get("code", "")))
        existing.add(str(s.get("ticker", "")))

    added = 0
    for key, val, item in EXTRA:
        if str(item[key]) in existing:
            continue
        data.append(item)
        added += 1
        existing.add(str(item["code"]))
        existing.add(str(item["ticker"]))

    with open(PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))

    print(f"all_stocks.json 修复完成：新增 {added} 条，总计 {len(data)} 条")
    for s in data[-6:]:
        print(" ", s["code"], s["name"], s["market"], s["board"])


if __name__ == "__main__":
    sys.exit(main())
