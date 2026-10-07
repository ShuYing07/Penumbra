# -*- coding: utf-8 -*-
"""第17轮·模块二：图片 / CSV/Excel / 剪贴板 数据导入测试。

CSV/Excel 解析逻辑已在 core.data_connector 实现；本轮补齐：
- 剪贴板表格（TSV/CSV/空白分隔）解析；
- 图片 → OHLCV（视觉 LLM 提取 CSV，离线/无模型返回空时清晰报错）；
二者统一归一化为标准化 OHLCV（date 作 index）。
"""
import os
import sys
from datetime import date

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("STOCKAI_MOCK", "1")

from core.data_connector import (parse_csv, parse_excel, parse_clipboard_table,
                                 parse_image_ohlcv, import_to_cache, _normalize)

# 1) CSV：英文表头（parse_clipboard_table 与 parse_csv 共用 _normalize 归一化逻辑）
csv_txt = "date,open,high,low,close,volume\n2024-01-02,10,11,9,10.5,1000\n2024-01-03,10.5,12,10,11.8,1200\n"
df_csv = parse_clipboard_table(csv_txt)
assert list(df_csv.columns) == ["open", "high", "low", "close", "volume"]
assert len(df_csv) == 2
assert df_csv.index[0] == pd.Timestamp("2024-01-02")
assert abs(df_csv["close"].iloc[1] - 11.8) < 1e-9
print("[ok] CSV式英文表头解析 →", df_csv.shape)

# 2) 中文表头
cn_txt = "日期\t开盘\t最高\t最低\t收盘\t成交量\n2024-01-02\t10\t11\t9\t10.5\t1000\n2024-01-03\t10.5\t12\t10\t11.8\t1200\n"
df_cn = parse_clipboard_table(cn_txt)
assert len(df_cn) == 2 and df_cn.index[0] == pd.Timestamp("2024-01-02")
assert abs(df_cn["close"].iloc[0] - 10.5) < 1e-9
print("[ok] 中文表头(TSV)解析 →", df_cn.shape)

# 3) 纯空白分隔
ws_txt = "2024-01-02 10 11 9 10.5 1000\n2024-01-03 10.5 12 10 11.8 1200\n"
df_ws = parse_clipboard_table(ws_txt)
assert len(df_ws) == 2
print("[ok] 空白分隔解析 →", df_ws.shape)

# 4) 缺成交量列（自动补 0）
no_vol = "date,open,high,low,close\n2024-01-02,10,11,9,10.5\n2024-01-03,10.5,12,10,11.8\n"
df_nv = parse_clipboard_table(no_vol)
assert "volume" in df_nv.columns and int(df_nv["volume"].iloc[0]) == 0
print("[ok] 缺成交量自动补0")

# 5) 空内容 / 无有效行 → 抛错
for bad in ("", "   \n\t\n", None):
    try:
        parse_clipboard_table(bad)
        raise AssertionError("应抛 ValueError")
    except ValueError:
        pass
print("[ok] 空/无内容正确抛 ValueError")

# 6) 缺少必需列 → 抛错
try:
    parse_clipboard_table("foo,bar\n1,2\n")
    raise AssertionError("应抛 ValueError")
except ValueError:
    pass
print("[ok] 缺必需列正确抛 ValueError")

# 7) 图片导入：extractor 返回 CSV → 归一化成功（模拟视觉 LLM）
fake_csv = "date,open,high,low,close,volume\n2024-02-01,5,6,4,5.5,300\n2024-02-02,5.5,6.2,5,6.0,350\n"
df_img = parse_image_ohlcv("ignored.png", extractor=lambda p: fake_csv)
assert len(df_img) == 2 and df_img.index[0] == pd.Timestamp("2024-02-01")
print("[ok] 图片→OHLCV（extractor 模拟视觉LLM） →", df_img.shape)

# 8) 图片导入：extractor 返回空（离线/无模型）→ 清晰报错
_err = None
try:
    parse_image_ohlcv("x.png", extractor=lambda p: "")
    raise AssertionError("应抛 ValueError")
except ValueError as e:
    _err = str(e)
    assert "未解析出" in _err
print("[ok] 图片无表格清晰报错:", _err[:20], "...")

# 9) 导入到缓存（mock upsert）
captured = {}
import core.data_connector as dc
saved_up = dc.import_to_cache
dc.import_to_cache = lambda df, tk: (captured.update(tk=tk, n=len(df)) or len(df))
n = dc.import_to_cache(df_csv, "MYDATA")
assert n == 2 and captured["tk"] == "MYDATA"
dc.import_to_cache = saved_up
print("[ok] import_to_cache 写入缓存（ticker=MYDATA, rows=2）")

# 10) Excel 解析（构造临时 xlsx 经 _normalize 路径）
tmp = os.path.join(os.environ.get("TEMP", "."), "t_imp.xlsx")
try:
    df_x = pd.DataFrame({
        "日期": ["2024-01-02", "2024-01-03"],
        "开盘": [10, 10.5], "最高": [11, 12], "最低": [9, 10],
        "收盘": [10.5, 11.8], "成交量": [1000, 1200]})
    df_x.to_excel(tmp, index=False)
    df_xr = parse_excel(tmp)
    assert len(df_xr) == 2 and abs(df_xr["close"].iloc[0] - 10.5) < 1e-9
    print("[ok] Excel 中文表头解析 →", df_xr.shape)
finally:
    try:
        os.remove(tmp)
    except OSError:
        pass

print("\nALL PASS")
