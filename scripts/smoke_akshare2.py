# -*- coding: utf-8 -*-
"""验证 akshare 备选数据源：腾讯K线 / 新浪K线 / 东财新闻 / 财联社。"""
import os
import time

os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"
for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
    os.environ.pop(k, None)

import akshare as ak


def trial(name, fn):
    print(f"\n[{name}] ...")
    t0 = time.time()
    try:
        df = fn()
        print(f"  OK 行数={len(df)} 耗时={time.time()-t0:.1f}s 列={list(df.columns)[:10]}")
        print(df.tail(2).to_string(max_cols=10))
    except Exception as e:
        print(f"  FAIL {type(e).__name__}: {str(e)[:200]}")


trial("腾讯日线 stock_zh_a_hist_tx(qfq)", lambda: ak.stock_zh_a_hist_tx(symbol="sh600519", adjust="qfq"))
trial("新浪日线 stock_zh_a_daily(qfq)", lambda: ak.stock_zh_a_daily(symbol="sh600519", adjust="qfq"))
trial("东财个股新闻 stock_news_em", lambda: ak.stock_news_em(symbol="600519"))
trial("财联社电报 stock_zh_a_alerts_cls", lambda: ak.stock_zh_a_alerts_cls())
trial("A股实时快照 stock_zh_a_spot_em(取列)", lambda: ak.stock_zh_a_spot_em())
