# -*- coding: utf-8 -*-
"""Tushare A股数据源（前复权日线 + 基本面），作为 akshare 的备源。

- token 从 .env 的 TUSHARE_TOKEN 读；
- fetch_daily_cn 与 akshare_source 同构（index=date, cols=open/high/low/close/volume/amount）；
- fetch_fundamental 给 pe/pb/ps/total_mv/turnover；
- 新注册账号积分较低，部分接口（daily/daily_basic）可能无权限，调用方需 try 降级。
"""
from __future__ import annotations

import logging
import os

import pandas as pd

log = logging.getLogger("stockai.data.tushare")

_PRO = None


def _token() -> str:
    return os.environ.get("TUSHARE_TOKEN", "").strip()


def _get_pro():
    global _PRO
    if _PRO is not None:
        return _PRO
    tok = _token()
    if not tok:
        raise RuntimeError("未配置 TUSHARE_TOKEN")
    import tushare as ts
    ts.set_token(tok)
    _PRO = ts.pro_api()
    return _PRO


def _ts_code(ticker: str) -> str:
    """sh600519 → 600519.SH；sz000001 → 000001.SZ。"""
    t = ticker.upper()
    code = t[2:]
    return f"{code}.SH" if t.startswith("SH") else f"{code}.SZ"


def _f(v) -> float | None:
    try:
        if v is None or pd.isna(v):
            return None
        return float(v)
    except Exception:  # noqa: BLE001
        return None


def fetch_daily_cn(ticker: str, days: int = 500) -> pd.DataFrame:
    """前复权日线，与 akshare 同构。新号无 daily 权限会抛错，调用方降级。"""
    code = _ts_code(ticker)
    import tushare as ts
    df = ts.pro_bar(ts_code=code, adj="qfq", freq="D")
    df = df.sort_values("trade_date").tail(days).copy()
    out = pd.DataFrame({
        "date": pd.to_datetime(df["trade_date"]),
        "open": df["open"].astype(float).values,
        "high": df["high"].astype(float).values,
        "low": df["low"].astype(float).values,
        "close": df["close"].astype(float).values,
        "volume": df["vol"].astype(float).values,
        "amount": df["amount"].astype(float).values if "amount" in df else None,
    }).set_index("date").sort_index()
    log.info("Tushare 日线 %s 行数=%d", code, len(out))
    return out


def fetch_fundamental(ticker: str) -> dict:
    """最新估值：pe_ttm/pb/ps_ttm/total_mv/turnover_rate。"""
    pro = _get_pro()
    code = _ts_code(ticker)
    db = pro.daily_basic(ts_code=code,
                         fields="trade_date,pe_ttm,pb,ps_ttm,total_mv,turnover_rate")
    if db is None or db.empty:
        return {}
    r = db.iloc[0]
    return {
        "source": "tushare",
        "pe": _f(r.get("pe_ttm")),
        "pb": _f(r.get("pb")),
        "ps": _f(r.get("ps_ttm")),
        "total_mv_yi": round(_f(r.get("total_mv")) / 10000.0, 1) if r.get("total_mv") else None,
        "turnover": _f(r.get("turnover_rate")),
    }
