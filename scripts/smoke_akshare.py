# -*- coding: utf-8 -*-
"""验证 akshare 在不同代理策略下的连通性。"""
import os
import time
import sys

# 策略 A：强制全部绕过代理（国内源直连）
os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"
for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
    os.environ.pop(k, None)

import akshare as ak

print("[A] akshare 强制直连(NO_PROXY=*) 取 600519 ...")
t0 = time.time()
try:
    df = ak.stock_zh_a_hist(symbol="600519", period="daily", adjust="qfq")
    print(f"  OK 行数={len(df)} 耗时={time.time()-t0:.1f}s")
    print("  列名:", list(df.columns))
    print(df.tail(2).to_string(max_cols=12))
except Exception as e:
    print(f"  FAIL {type(e).__name__}: {e}")
    sys.exit(1)

print("\n[B] akshare 财联社电报(新闻) ...")
t0 = time.time()
try:
    df2 = ak.stock_zh_a_alerts_cls()
    print(f"  OK 行数={len(df2)} 耗时={time.time()-t0:.1f}s")
    print("  列名:", list(df2.columns))
    print(df2.head(3).to_string(max_cols=6))
except Exception as e:
    print(f"  FAIL {type(e).__name__}: {e}")

print("\n[C] akshare 个股新闻 stock_news_em ...")
t0 = time.time()
try:
    df3 = ak.stock_news_em(symbol="600519")
    print(f"  OK 行数={len(df3)} 耗时={time.time()-t0:.1f}s")
    print("  列名:", list(df3.columns))
    print(df3.head(3).to_string(max_cols=6))
except Exception as e:
    print(f"  FAIL {type(e).__name__}: {e}")
