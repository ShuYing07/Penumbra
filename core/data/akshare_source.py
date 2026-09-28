# -*- coding: utf-8 -*-
"""A股数据源（akshare + 新浪实时）。

连通性结论（2026-09-10 实测）：
- push2his.eastmoney.com 的 HTTPS:443 在本机 TUN 环境下持续被断连（HTTP:80 正常），
  因此日线优先级：新浪 stock_zh_a_daily（快、稳）→ 腾讯 stock_zh_a_hist_tx → 东财。
- 实时报价 hq.sinajs.cn、个股新闻 stock_news_em、财联社 stock_info_global_cls 均正常。
"""
from __future__ import annotations

import logging
import threading

import pandas as pd
import requests

from core.config import domestic_network

log = logging.getLogger("stockai.data.akshare")

# akshare 新浪源内部用 py_mini_racer(V8) 解析 JS；V8 初始化非线程安全，
# 多线程并发首次调用会偶发崩溃（0xC0000409，仅冻结环境出现）。
# 统一串行化新浪相关 akshare 调用（日线/指数日线），根治该崩溃。
_SINA_LOCK = threading.Lock()

_COLS = ["open", "high", "low", "close", "volume", "amount"]


def cn_symbol(ticker: str) -> str:
    """SH600519 / SZ000001 → sh600519 / sz000001。"""
    t = ticker.upper()
    return t.lower()


def cn_code6(ticker: str) -> str:
    return ticker.upper()[2:]


def _norm(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    for c in _COLS:
        if c not in df.columns:
            df[c] = None
    return df[_COLS]


def _daily_sina(ak, sym: str) -> pd.DataFrame:
    """新浪前复权日线（股票；ETF 不支持，会抛 JSONDecodeError）。"""
    with _SINA_LOCK:  # mini_racer(V8) 非线程安全，必须串行
        with domestic_network():
            raw = ak.stock_zh_a_daily(symbol=sym, adjust="qfq")
    return _norm(raw.rename(columns=str.lower))


def _daily_tencent(ak, sym: str) -> pd.DataFrame:
    """腾讯前复权日线（股票/ETF 均支持；多出的 turnover 列由 _norm 裁剪）。"""
    with domestic_network():
        raw = ak.stock_zh_a_hist_tx(symbol=sym, adjust="qfq")
    return _norm(raw.rename(columns=str.lower))


def _daily_eastmoney(ak, code: str, etf: bool = False) -> pd.DataFrame:
    """东财前复权日线（部分网络环境 443 不可用；ETF 走 fund_etf_hist_em）。"""
    with domestic_network():
        if etf:
            raw = ak.fund_etf_hist_em(symbol=code, period="daily", adjust="qfq")
        else:
            raw = ak.stock_zh_a_hist(symbol=code, period="daily", adjust="qfq")
    return _norm(raw.rename(columns={
        "日期": "date", "开盘": "open", "收盘": "close", "最高": "high",
        "最低": "low", "成交量": "volume", "成交额": "amount",
    }))


def fetch_daily_cn(ticker: str) -> pd.DataFrame:
    """A股前复权日线，多源降级。失败抛最后一个异常。

    实测（2026-09-11）：新浪 stock_zh_a_daily 不支持场内 ETF，
    故 ETF 顺序=腾讯→东财(fund_etf_hist_em)；股票顺序=新浪→腾讯→东财。
    """
    import akshare as ak

    from core.data.service import is_cn_etf

    sym, code = cn_symbol(ticker), cn_code6(ticker)
    etf = is_cn_etf(ticker)
    last_err: Exception | None = None

    if etf:
        sources = [
            ("tencent", lambda: _daily_tencent(ak, sym)),
            ("eastmoney(etf)", lambda: _daily_eastmoney(ak, code, etf=True)),
        ]
    else:
        sources = [
            ("sina", lambda: _daily_sina(ak, sym)),
            ("tencent", lambda: _daily_tencent(ak, sym)),
            ("eastmoney", lambda: _daily_eastmoney(ak, code)),
        ]

    for name, fn in sources:
        try:
            log.info("A股日线尝试源：%s %s%s", name, sym, "(ETF)" if etf else "")
            df = fn()
            log.info("A股日线 %s 来源=%s 行数=%d", ticker, name, len(df))
            return df
        except Exception as e:  # noqa: BLE001
            last_err = e
            log.warning("%s 日线失败 %s: %s", name, ticker, e)
    # 最后兜底：Tushare（新号积分不足时静默失败）
    try:
        from core.data import tushare_source
        log.info("A股日线尝试源：tushare %s", sym)
        df = tushare_source.fetch_daily_cn(ticker)
        log.info("A股日线 %s 来源=tushare 行数=%d", ticker, len(df))
        return df
    except Exception as e:  # noqa: BLE001
        log.warning("tushare 日线失败 %s: %s", ticker, e)
    raise last_err if last_err else RuntimeError(f"全部日线源失败: {ticker}")


def fetch_realtime_cn(ticker: str) -> dict:
    """新浪实时报价。交易时段为现价，收盘后为最新收盘价。"""
    sym = cn_symbol(ticker)
    with domestic_network():
        resp = requests.get(
            f"https://hq.sinajs.cn/list={sym}",
            headers={"Referer": "https://finance.sina.com.cn"},
            timeout=10,
        )
    resp.encoding = "gbk"
    payload = resp.text.split('"')[1].split(",")
    if len(payload) < 32 or not payload[3]:
        raise RuntimeError(f"新浪实时报价为空: {ticker}")
    return {
        "name": payload[0],
        "open": float(payload[1]),
        "prev_close": float(payload[2]),
        "price": float(payload[3]),
        "high": float(payload[4]),
        "low": float(payload[5]),
        "volume": float(payload[8]),
        "amount": float(payload[9]),
        "date": payload[30],
        "time": payload[31],
        "chg_pct": round((float(payload[3]) / float(payload[2]) - 1) * 100, 2),
    }


def fetch_news_cn(ticker: str, limit: int = 10) -> list[dict]:
    import akshare as ak

    code = cn_code6(ticker)
    with domestic_network():
        df = ak.stock_news_em(symbol=code)
    items = []
    for _, r in df.head(limit).iterrows():
        items.append({
            "ticker": ticker,
            "title": str(r.get("新闻标题", "")).strip(),
            "content": str(r.get("新闻内容", "")).strip()[:600],
            "source": str(r.get("文章来源", "东方财富")),
            "url": str(r.get("新闻链接", "")),
            "published_at": str(r.get("发布时间", "")),
        })
    return items


def fetch_info_cn(ticker: str) -> dict:
    """东财 F10 个股资料（接口失败时返回空 dict，不阻断流程）。"""
    import akshare as ak

    try:
        with domestic_network():
            df = ak.stock_individual_info_em(symbol=cn_code6(ticker))
        out = {str(r["item"]): str(r["value"]) for _, r in df.iterrows()}
        return {
            "name": out.get("股票简称"),
            "industry": out.get("行业"),
            "total_market_cap": out.get("总市值"),
            "circulating_market_cap": out.get("流通市值"),
            "pe_ttm": out.get("市盈率(动态)"),
            "pb": out.get("市净率"),
            "list_date": out.get("上市时间"),
        }
    except Exception as e:  # noqa: BLE001
        log.warning("F10 资料失败 %s: %s", ticker, e)
        return {}


# ---------------------------------------------------------------------------
# A股指数日线（模块一：修复沪深300等指数历史数据缺失）
# 优先级：东财 index_zh_a_hist（支持日期区间）→ 新浪 stock_zh_index_daily（全历史）
#         → Tushare index_daily → yfinance（service 层兜底）
# ---------------------------------------------------------------------------
def fetch_daily_index(ticker: str,
                      start_date: str = "19900101",
                      end_date: str | None = None) -> pd.DataFrame:
    """A股指数前复权日线。ticker 为 6 位指数代码（如 '000300'，已在 service.INDEX_MAP 注册）。

    - 东财 index_zh_a_hist：实测可返回 6000+ 行（沪深300 自 2002 年起），支持区间切片；
    - 新浪 stock_zh_index_daily：全历史兜底，仅 date/open/high/low/close/volume；
    - Tushare index_daily：积分号可用时兜底。
    """
    import akshare as ak

    from core.config import now_cn
    from core.data.service import INDEX_MAP

    if ticker not in INDEX_MAP:
        raise ValueError(f"未注册的指数代码: {ticker}")
    entry = INDEX_MAP[ticker]
    end_date = end_date or now_cn().strftime("%Y%m%d")
    last_err: Exception | None = None

    # 1) 东财（支持 start/end 区间；本机 TUN 下 443 可能被断，失败自动降级）
    try:
        with domestic_network():
            raw = ak.index_zh_a_hist(symbol=entry["akshare"], period="daily",
                                     start_date=start_date, end_date=end_date)
        df = _norm(raw.rename(columns={
            "日期": "date", "开盘": "open", "收盘": "close", "最高": "high",
            "最低": "low", "成交量": "volume", "成交额": "amount",
        }))
        log.info("指数日线 %s 来源=eastmoney 行数=%d", ticker, len(df))
        return df
    except Exception as e:  # noqa: BLE001
        last_err = e
        log.warning("指数日线 eastmoney 失败 %s: %s", ticker, e)

    # 2) 新浪（全历史；列名为英文小写）
    try:
        with _SINA_LOCK:  # mini_racer(V8) 非线程安全，必须串行
            with domestic_network():
                raw = ak.stock_zh_index_daily(symbol=entry["sina"])
        df = _norm(raw.rename(columns=str.lower))
        log.info("指数日线 %s 来源=sina 行数=%d", ticker, len(df))
        return df
    except Exception as e:  # noqa: BLE001
        last_err = e
        log.warning("指数日线 sina 失败 %s: %s", ticker, e)

    # 3) Tushare（需 TUSHARE_TOKEN；新号积分不足时静默失败）
    try:
        from core.data import tushare_source
        df = tushare_source.fetch_index_daily(entry["tushare"].split(".")[0])
        log.info("指数日线 %s 来源=tushare 行数=%d", ticker, len(df))
        return df
    except Exception as e:  # noqa: BLE001
        log.warning("指数日线 tushare 失败 %s: %s", ticker, e)

    raise last_err if last_err else RuntimeError(f"全部指数日线源失败: {ticker}")


def fetch_realtime_index(ticker: str) -> dict:
    """新浪指数实时报价（sh000300 / sz399001 等）。字段与股票实时一致。"""
    from core.data.service import INDEX_MAP

    if ticker not in INDEX_MAP:
        raise ValueError(f"未注册的指数代码: {ticker}")
    sym = INDEX_MAP[ticker]["sina"]
    with domestic_network():
        resp = requests.get(
            f"https://hq.sinajs.cn/list={sym}",
            headers={"Referer": "https://finance.sina.com.cn"},
            timeout=10,
        )
    resp.encoding = "gbk"
    payload = resp.text.split('"')[1].split(",")
    if len(payload) < 32 or not payload[3]:
        raise RuntimeError(f"新浪指数实时为空: {ticker}")
    prev = float(payload[2])
    price = float(payload[3])
    return {
        "name": payload[0],
        "open": float(payload[1]),
        "prev_close": prev,
        "price": price,
        "high": float(payload[4]),
        "low": float(payload[5]),
        "volume": float(payload[8]),
        "amount": float(payload[9]),
        "date": payload[30],
        "time": payload[31],
        "chg_pct": round((price / prev - 1) * 100, 2) if prev else None,
    }
