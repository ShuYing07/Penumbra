# -*- coding: utf-8 -*-
"""数据服务门面：市场识别 → 选源 → 拉取 → point-in-time 缓存 → 统一返回。

规范标的代码：
- A股：SH600519 / SZ000001
- 美股：AAPL
- 港股/日股等：0700.HK / 7203.T（yfinance 格式）
- 加密：BTC-USD / ETH-USD
"""
from __future__ import annotations

import logging
import re

import pandas as pd

from core.data import akshare_source as ak_src
from core.data import cache, news_sources, yfinance_source as yf_src
from core.config import now_cn

log = logging.getLogger("stockai.data")


# ---------------------------------------------------------------------------
# A股指数映射（模块一）
# 各数据源代码与名称；000001 刻意不在默认表内——它是深市"平安银行"股票代码，
# 若要上证指数请输入 sh000001（可自行在本表追加后重启）。
# 降级链：AKShare(index_zh_a_hist→sina) → Tushare(index_daily) → yfinance → 缓存兜底
# ---------------------------------------------------------------------------
INDEX_MAP: dict[str, dict] = {
    "000300": {"akshare": "000300", "yfinance": "000300.SS", "tushare": "000300.SH",
               "sina": "sh000300", "name": "沪深300"},
    "000905": {"akshare": "000905", "yfinance": "000905.SS", "tushare": "000905.SH",
               "sina": "sh000905", "name": "中证500"},
    "000016": {"akshare": "000016", "yfinance": "000016.SS", "tushare": "000016.SH",
               "sina": "sh000016", "name": "上证50"},
    "000688": {"akshare": "000688", "yfinance": "000688.SS", "tushare": "000688.SH",
               "sina": "sh000688", "name": "科创50"},
    "000852": {"akshare": "000852", "yfinance": "000852.SS", "tushare": "000852.SH",
               "sina": "sh000852", "name": "中证1000"},
    "000903": {"akshare": "000903", "yfinance": "000903.SS", "tushare": "000903.SH",
               "sina": "sh000903", "name": "中证100"},
    "000010": {"akshare": "000010", "yfinance": "000010.SS", "tushare": "000010.SH",
               "sina": "sh000010", "name": "上证180"},
    "000009": {"akshare": "000009", "yfinance": "000009.SS", "tushare": "000009.SH",
               "sina": "sh000009", "name": "上证380"},
    "399001": {"akshare": "399001", "yfinance": "399001.SZ", "tushare": "399001.SZ",
               "sina": "sz399001", "name": "深证成指"},
    "399006": {"akshare": "399006", "yfinance": "399006.SZ", "tushare": "399006.SZ",
               "sina": "sz399006", "name": "创业板指"},
    "399005": {"akshare": "399005", "yfinance": "399005.SZ", "tushare": "399005.SZ",
               "sina": "sz399005", "name": "中小100"},
    "399300": {"akshare": "399300", "yfinance": "399300.SZ", "tushare": "399300.SZ",
               "sina": "sz399300", "name": "沪深300(深)"},
}


def index_code_of(raw: str) -> str | None:
    """从用户输入提取已注册的 6 位指数代码：
    '000300' / 'sh000300' / 'SH000300' / '000300.SS' / '000300.SH' → '000300'；否则 None。"""
    t = raw.strip().upper()
    if not t:
        return None
    bare = re.sub(r"^(SH|SZ|BJ)", "", t)
    bare = re.sub(r"\.(SS|SZ|SH|SSE|SHS)$", "", bare)
    if re.fullmatch(r"\d{6}", bare) and bare in INDEX_MAP:
        return bare
    return None


def normalize_ticker(raw: str) -> str:
    """用户输入标准化：
    - 指数：'000300' / 'sh000300' / '000300.SS' → '000300'（命中 INDEX_MAP 时直通）
    - '600519' → 'SH600519'（6/5/9开头→沪市）
    - '000001' → 'SZ000001'（0/3/1/2/4/7/8开头→深市）
    - 已带 SH/SZ/BJ 前缀或含 . / - 的原样返回
    """
    t = raw.strip().upper()
    if not t:
        return t
    idx = index_code_of(t)
    if idx:
        return idx
    if re.match(r"^(SH|SZ|BJ)\d", t) or "." in t or "-" in t:
        return t
    if re.fullmatch(r"\d{6}", t):
        return ("SH" if t[0] in "659" else "SZ") + t
    return t


def market_of(ticker: str) -> str:
    t = normalize_ticker(ticker)
    if re.fullmatch(r"\d{6}", t) and t in INDEX_MAP:
        return "CN_INDEX"
    if re.fullmatch(r"(SH|SZ)\d{6}", t):
        return "CN"
    if re.fullmatch(r"[A-Z0-9]{2,15}-(USD|USDT|USDC)", t):
        return "CRYPTO"
    if re.fullmatch(r"\d{4,5}\.HK", t):
        return "HK"   # 港股须在通用 "." 分支之前（0700.HK / 00700.HK）
    if re.fullmatch(r"\d{4}\.T", t):
        return "JP"   # 日股：7203.T（丰田）
    if re.fullmatch(r"\d{6}\.KS", t):
        return "KR"   # 韩股：005930.KS（三星）
    if re.fullmatch(r"\d{4}\.TW", t):
        return "TW"   # 台股：2330.TW（台积电）
    if re.fullmatch(r"[A-Z.]{1,10}", t) and "." not in t and re.fullmatch(r"[A-Z]{1,6}", t):
        return "US"
    if "." in t:
        return "GLOBAL"
    return "UNKNOWN"


# 沪深场内 ETF 号段：沪市 51x/56x/58x（510/512/513/515/516/518/588 等），深市 159 段
_RE_CN_ETF = re.compile(r"(?:SH(?:51|56|58)\d{4}|SZ159\d{3})")


def is_cn_etf(ticker: str) -> bool:
    """是否沪深场内 ETF（日线须走腾讯源；回测免印花税/过户费）。"""
    return bool(_RE_CN_ETF.fullmatch(ticker.upper()))


def security_type(ticker: str) -> str:
    """标的类型：仅区分 A股场内 ETF；其余一律 STOCK（美股 ETF 费率与股票同，无需区分）。"""
    if market_of(ticker) == "CN" and is_cn_etf(ticker):
        return "ETF"
    return "STOCK"


def _try_fallback_source(ticker: str, market: str) -> None:
    """数据质量不合格时的备源尝试：仅对 A 股/指数有可用备源，失败静默。

    指数：上游 ak_src.fetch_daily_index 内部已做 东财→新浪→Tushare 降级；
    此处补充 yfinance 兜底。A 股：akshare 内部已做新浪/东财降级，不重复联网。
    """
    try:
        if market == "CN_INDEX":
            yf_code = INDEX_MAP.get(ticker, {}).get("yfinance")
            if yf_code:
                from core.data import yfinance_source as yf_src
                df2 = yf_src.fetch_daily_global(yf_code)
                if df2 is not None and len(df2) > 0:
                    cache.upsert_bars(ticker, df2, "fallback-yf")
                    log.info("备源 yfinance 回填 %s %d 行", ticker, len(df2))
    except Exception as e:  # noqa: BLE001
        log.warning("备源回填失败 %s: %s", ticker, e)


def get_daily(ticker: str, use_cache: bool = True) -> tuple[pd.DataFrame, str]:
    """返回 (日线DataFrame, 数据状态说明)。优先读缓存，缺失/陈旧则联网增量补取。"""
    from core.performance_monitor import perf
    perf.record_api("get_daily")
    ticker = normalize_ticker(ticker)
    market = market_of(ticker)
    cached = cache.load_bars(ticker)
    today = now_cn().strftime("%Y-%m-%d")

    last_dt = cached.index.max().strftime("%Y-%m-%d") if len(cached) > 0 else "1970-01-01"
    # 新鲜度：缓存最后日期距今 ≤7 个自然日即视为可用（覆盖周末/长假/数据源滞后，避免反复联网）
    stale_days = (pd.Timestamp(today) - pd.Timestamp(last_dt)).days
    fresh = len(cached) > 0 and stale_days <= 7
    if use_cache and len(cached) >= 60 and fresh:
        return cached, "cache"

    try:
        if market == "CN_INDEX":
            # 指数：AKShare(东财→新浪→Tushare) 主链，失败再走 yfinance 兜底
            try:
                new_df = ak_src.fetch_daily_index(ticker)
            except Exception as e:  # noqa: BLE001
                log.warning("指数 A股源失败 %s: %s；尝试 yfinance 兜底", ticker, e)
                new_df = yf_src.fetch_daily_global(INDEX_MAP[ticker]["yfinance"])
        elif market == "CN":
            new_df = ak_src.fetch_daily_cn(ticker)
        elif market in ("US", "HK", "GLOBAL", "CRYPTO"):
            new_df = yf_src.fetch_daily_global(ticker)
        else:
            raise ValueError(f"无法识别标的: {ticker}")
        added = cache.upsert_bars(ticker, new_df, "network")
        log.info("行情入库 %s 新增 %d 行", ticker, added)
        # 数据质量校验（任务书A·模块二）：不合格时记 warning 并尝试备源
        try:
            from core.data_quality import validate_stock_data
            _q = validate_stock_data(new_df)
            if not _q["passed"]:
                log.warning("数据质量校验未通过 %s: %s（score=%.1f）",
                            ticker, "; ".join(_q["issues"][:3]), _q["score"])
                _try_fallback_source(ticker, market)
        except Exception:  # noqa: BLE001
            pass
        return cache.load_bars(ticker), f"network(+{added})"
    except Exception as e:  # noqa: BLE001
        if len(cached) > 0:
            log.warning("联网取数失败 %s: %s；使用缓存 %d 行", ticker, e, len(cached))
            return cached, f"cache-fallback({type(e).__name__})"
        raise


def get_realtime(ticker: str) -> dict:
    from core.performance_monitor import perf
    perf.record_api("get_realtime")
    market = market_of(ticker)
    try:
        if market == "CN_INDEX":
            r = ak_src.fetch_realtime_index(ticker)
        elif market == "CN":
            r = ak_src.fetch_realtime_cn(ticker)
        else:
            r = yf_src.fetch_realtime_global(ticker)
    except Exception as e:  # noqa: BLE001
        log.warning("实时报价失败 %s: %s", ticker, e)
        r = {}
    # 休市/盘口为空（price<=0）时，用日线最新收盘兜底，避免显示 0 / -100%
    if not r.get("price") or float(r.get("price") or 0) <= 0:
        bars = cache.load_bars(ticker)
        if len(bars) < 2:
            try:
                bars, _ = get_daily(ticker)
            except Exception:  # noqa: BLE001
                pass
        if len(bars) >= 2:
            last, prev = float(bars["close"].iloc[-1]), float(bars["close"].iloc[-2])
            r.update({
                "price": round(last, 4), "prev_close": round(prev, 4),
                "chg_pct": round((last / prev - 1) * 100, 2),
                "date": bars.index[-1].strftime("%Y-%m-%d"), "source": "daily_close",
            })
        elif len(bars) == 1:
            r.update({"price": round(float(bars["close"].iloc[-1]), 4), "chg_pct": None})
    return r


def get_fundamentals(ticker: str) -> dict:
    market = market_of(ticker)
    if market == "CN_INDEX":
        return {"note": "指数无个股财报：应关注成分股构成、估值分位（PE/PB 历史百分位）与成交额"}
    if market == "CN":
        if is_cn_etf(ticker):
            return {"note": "场内基金/ETF：无传统个股财报指标，应关注跟踪指数、折溢价与成交额"}
        return ak_src.fetch_info_cn(ticker)
    if market == "CRYPTO":
        return {"note": "加密资产无传统财报/估值指标"}
    return yf_src.fetch_info_global(ticker)


def get_news(ticker: str, per_symbol_limit: int = 8) -> list[dict]:
    """个股新闻（落库）+ 财联社宏观快讯（A股附带）。"""
    market = market_of(ticker)
    items: list[dict] = []
    try:
        if market == "CN_INDEX":
            # 指数无个股新闻：仅拉财联社宏观快讯（下方 macro 逻辑统一处理）
            items = []
        elif market == "CN":
            items = ak_src.fetch_news_cn(ticker, per_symbol_limit)
            try:
                from core.data import tavily_news
                items = items + tavily_news.search(
                    f"{ak_src.cn_code6(ticker)} A股 最新消息", 5)
            except Exception as e:  # noqa: BLE001
                log.warning("Tavily新闻失败（降级）：%s", e)
        else:
            items = yf_src.fetch_news_global(ticker, per_symbol_limit)
    except Exception as e:  # noqa: BLE001
        log.warning("个股新闻失败 %s: %s", ticker, e)
    cache.upsert_news(items)

    macro: list[dict] = []
    if market in ("CN", "CN_INDEX"):
        macro = news_sources.cls_global(limit=10)
        cache.upsert_news(macro)
    return items + macro


def _last_trade_day_hint(today_iso: str) -> str:
    """粗略的最近交易日（仅判断缓存新鲜度；周末回退到周五，节假日允许再联网尝试）。"""
    d = pd.Timestamp(today_iso)
    if d.weekday() == 5:  # 周六
        d -= pd.Timedelta(days=1)
    elif d.weekday() == 6:  # 周日
        d -= pd.Timedelta(days=2)
    return d.strftime("%Y-%m-%d")
