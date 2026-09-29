# -*- coding: utf-8 -*-
"""Agent 可调用工具：把现有数据/指标/新闻/回测/搜索能力封装为带 Schema 的工具。

参考 iFinD MCP：每个工具用自然语言描述输入输出，让 LLM 能理解
"当用户问 X 时该调用哪个工具、传什么参数"。
"""
from __future__ import annotations

import json
import logging
from functools import lru_cache
from typing import Any, Callable, Dict, List

from agent.schemas import (BacktestIn, DrawingsIn, FetchStockIn, IndicatorsIn,
                           MarketOverviewIn, NewsIn, RealtimeIn,
                           ScreenerIn, SearchStocksIn, ToolResult,
                           fail_result, ok_result)
from core.data import service
from core.quant import indicators as ind
from core.quant.backtest import STRATEGY_META, run_backtest

log = logging.getLogger("stockai.agent.tools")


# ---------------------------------------------------------------------------
# 股票索引（all_stocks.json，带内存缓存）
# ---------------------------------------------------------------------------
@lru_cache(maxsize=1)
def _stocks_index() -> List[dict]:
    import os
    from pathlib import Path
    p = Path(__file__).resolve().parents[1] / "data" / "all_stocks.json"
    if not p.exists():
        return []
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def _resolve_code(raw: str) -> str:
    """把用户输入归一化为标准代码（600519→SH600519，保留 AAPL/0700.HK）。"""
    return service.normalize_ticker(raw.strip().upper())


# ---------------------------------------------------------------------------
# 工具实现
# ---------------------------------------------------------------------------
def fetch_stock_data(code: str) -> ToolResult:
    """获取行情数据 + 技术指标快照（客观数值，不含建议）。"""
    ticker = _resolve_code(code)
    df, src = service.get_daily(ticker)
    if df is None or len(df) < 2:
        return fail_result("fetch_stock_data", f"{ticker} 数据不足")
    snap = ind.latest_snapshot(df)
    last5 = df.tail(5).reset_index()
    recent = [
        {"date": str(r["日期"]) if "日期" in df.columns else str(i),
         "close": float(r["close"]), "chg_pct": float(r.get("chg_pct", 0) or 0)}
        for i, r in last5.iterrows()
    ]
    data = {
        "code": ticker,
        "market": service.market_of(ticker),
        "source": src,
        "rows": int(len(df)),
        "asof": snap.get("asof"),
        "close": snap.get("close"),
        "chg_pct_1d": snap.get("chg_pct_1d"),
        "chg_pct_60d": (snap.get("chg_pct_periods") or {}).get(60),
        "rsi14": snap.get("rsi14"),
        "macd_signal": (snap.get("macd") or {}).get("signal"),
        "recent_5d": recent,
    }
    return ok_result("fetch_stock_data", data, f"数据源：{src}")


def calculate_indicators(code: str, indicators: List[str]) -> ToolResult:
    """计算指定技术指标的最新值。"""
    ticker = _resolve_code(code)
    df, src = service.get_daily(ticker)
    if df is None or len(df) < 30:
        return fail_result("calculate_indicators", f"{ticker} 数据不足")
    close = df["close"].astype(float)
    out: Dict[str, Any] = {"code": ticker, "source": src, "values": {}}
    for name in indicators:
        try:
            if name.startswith("sma"):
                n = int(name.replace("sma", "") or 20)
                v = ind.sma(close, n).iloc[-1]
                out["values"][name] = None if v != v else round(float(v), 2)
            elif name == "boll":
                mid, up, low = ind.boll(close)
                out["values"]["boll"] = {
                    "mid": round(float(mid.iloc[-1]), 2),
                    "up": round(float(up.iloc[-1]), 2),
                    "low": round(float(low.iloc[-1]), 2),
                }
            elif name == "rsi14":
                v = ind.rsi(close, 14).iloc[-1]
                out["values"]["rsi14"] = None if v != v else round(float(v), 2)
            elif name == "macd":
                d = ind.macd(close)
                out["values"]["macd"] = {
                    "DIF": round(float(d["DIF"].iloc[-1]), 3),
                    "DEA": round(float(d["DEA"].iloc[-1]), 3),
                    "HIST": round(float(d["HIST"].iloc[-1]), 3),
                    "signal": str(d.get("signal", "无交叉信号")),
                }
        except Exception as e:  # noqa: BLE001
            out["values"][name] = f"error:{e}"
    return ok_result("calculate_indicators", out, f"数据源：{src}")


def search_news(code: str, limit: int = 8) -> ToolResult:
    """检索相关新闻。"""
    ticker = _resolve_code(code)
    try:
        news = service.get_news(ticker, per_symbol_limit=limit)
    except Exception as e:  # noqa: BLE001
        return fail_result("search_news", f"{e}")
    items = [{"date": n.get("date", ""), "title": n.get("title", ""),
              "source": n.get("source", ""), "url": n.get("url", "")}
             for n in news[:limit]]
    return ok_result("search_news", {"code": ticker, "items": items},
                     "新闻仅供研究参考，不代表任何立场")


def run_backtest_tool(code: str, strategy: str = "ma_cross",
                      params: Dict | None = None) -> ToolResult:
    """运行策略回测，返回绩效指标。"""
    ticker = _resolve_code(code)
    df, src = service.get_daily(ticker)
    if df is None or len(df) < 60:
        return fail_result("run_backtest", f"{ticker} 历史数据不足（需 ≥60 根）")
    if strategy not in STRATEGY_META:
        return fail_result("run_backtest",
                           f"策略 {strategy} 不存在，可选：{', '.join(STRATEGY_META)}")
    try:
        from core.quant.backtest import BacktestConfig
        cfg = BacktestConfig(market=service.market_of(ticker), ticker=ticker)
        res = run_backtest(df, service.market_of(ticker), strategy,
                           params=params or None, config=cfg)
    except Exception as e:  # noqa: BLE001
        return fail_result("run_backtest", f"{e}")
    m = res.metrics
    eq = res.equity
    data = {
        "code": ticker,
        "strategy": strategy,
        "source": src,
        "metrics": m,
        "equity_head": [float(eq["strategy"].iloc[0]), float(eq["strategy"].iloc[-1])],
        "bars": int(len(df)),
    }
    return ok_result("run_backtest", data,
                     "历史回测不代表未来表现，不构成投资建议")


def search_stocks(query: str, market: str | None = None,
                  limit: int = 10) -> ToolResult:
    """按代码/名称/拼音检索股票。"""
    q = (query or "").strip().upper()
    if not q:
        return fail_result("search_stocks", "查询词为空")
    stocks = _stocks_index()
    hits: List[dict] = []
    # 尝试拼音缩写匹配（pypinyin 可选；未安装时跳过）
    pinyin_abbr: Dict[str, List[dict]] = {}
    for s in stocks:
        if s["market"] == market or market is None:
            code = s["code"]
            name = s["name"]
            if q in code or q in name.upper() or q in name:
                hits.append(s)
            elif len(hits) < limit * 3:
                pinyin_abbr.setdefault(_abbr(name), []).append(s)
    # 精确命中优先，其次拼音缩写
    pinyin_hits = pinyin_abbr.get(q.lower(), [])[:limit]
    for s in pinyin_hits:
        if s not in hits:
            hits.append(s)
    top = hits[:limit]
    return ok_result("search_stocks",
                     {"query": query, "hits": [
                         {"code": service.normalize_ticker(s["code"]),
                          "name": s["name"], "market": s["market"]}
                         for s in top]},
                     f"共匹配 {len(hits)} 条，展示前 {len(top)} 条")


@lru_cache(maxsize=1)
def _abbr(name: str) -> str:
    """中文名称→拼音首字母缩写（无 pypinyin 时退化为空）。"""
    try:
        from pypinyin import lazy_pinyin
        return "".join(w[0] for w in lazy_pinyin(name) if w and w[0].isalpha()).lower()
    except Exception:  # noqa: BLE001
        return ""


def get_market_overview() -> ToolResult:
    """今日市场概览：主要指数点位/涨跌（新浪实时，稳定）。"""
    from core.data.market_overview import list_market_indices
    indices = list_market_indices()
    note = "数据源：新浪实时行情"
    # 北向资金/两市成交额（东财接口，网络受限时静默降级，不阻塞主结果）
    extra = {}
    try:
        from core.config import domestic_network
        import akshare as ak
        with domestic_network():
            hsgt = ak.stock_hsgt_fund_flow_summary_em()
        _map = dict(zip(hsgt.iloc[:, 0].astype(str), hsgt.iloc[:, 1]))
        extra["northbound"] = {
            k: float(v) for k, v in _map.items() if "资金" in str(k) or "北向" in str(k)}
    except Exception as e:  # noqa: BLE001
        note += f"；北向资金不可达({type(e).__name__})已降级"
    return ok_result("get_market_overview",
                     {"indices": indices, "extra": extra}, note)


def get_realtime_snapshot(code: str) -> ToolResult:
    """股票实时快照。"""
    ticker = _resolve_code(code)
    try:
        data = service.get_realtime(ticker)
        return ok_result("get_realtime_snapshot", data)
    except Exception as e:  # noqa: BLE001
        return fail_result("get_realtime_snapshot", f"{e}")


def get_drawings(code: str) -> ToolResult:
    """读取用户绘制的标注（趋势线/水平线/斐波那契/矩形），供分析引用。"""
    ticker = _resolve_code(code)
    try:
        from core.drawings import list_drawings
        from core.data.service import get_daily
        draws = list_drawings(ticker)
        df, _src = get_daily(ticker)
        out = []
        if df is not None:
            for d in draws:
                pts = []
                for p in d["points"]:
                    x = int(p["x"])
                    date = str(df.index[x].date()) if 0 <= x < len(df) else f"idx{x}"
                    pts.append({"date": date, "price": p["y"]})
                out.append({"id": d["id"], "type": d["type"], "points": pts})
        return ok_result("get_drawings",
                         {"code": ticker, "drawings": out,
                          "hint": "用户标注用于辅助理解技术位，不构成建议"},
                         f"共 {len(out)} 条标注")
    except Exception as e:  # noqa: BLE001
        return fail_result("get_drawings", f"{e}")


# ---------------------------------------------------------------------------
# 工具注册表（供 AgentCore / MCP 使用）
# ---------------------------------------------------------------------------
def build_registry() -> Dict[str, Dict[str, Any]]:
    """name → {func, schema, description}。"""
    return {
        "fetch_stock_data": {
            "func": fetch_stock_data,
            "schema": FetchStockIn,
            "description": "获取一只股票的行情数据与技术指标快照（最新收盘、涨跌幅、RSI、MACD、近5日走势）。输入：股票代码。",
        },
        "calculate_indicators": {
            "func": calculate_indicators,
            "schema": IndicatorsIn,
            "description": "计算指定技术指标的最新值（sma5/10/20/60、boll、rsi14、macd）。输入：股票代码+指标名列表。",
        },
        "search_news": {
            "func": search_news,
            "schema": NewsIn,
            "description": "检索与某只股票相关的最近新闻。输入：股票代码。",
        },
        "run_backtest": {
            "func": run_backtest_tool,
            "schema": BacktestIn,
            "description": "对一只股票运行策略回测并返回绩效指标（总收益/年化/最大回撤/夏普/胜率/盈亏比）。输入：股票代码+策略名。策略：ma_cross/rsi_reversion/macd_cross/buy_hold。",
        },
        "search_stocks": {
            "func": search_stocks,
            "schema": SearchStocksIn,
            "description": "按代码、名称或拼音缩写检索股票（如 gzmt→贵州茅台）。输入：查询词+可选市场过滤。",
        },
        "get_market_overview": {
            "func": get_market_overview,
            "schema": MarketOverviewIn,
            "description": "获取今日市场概览：上证/深证/创业板/沪深300指数点位涨跌、北向资金净流入、两市成交额。",
        },
        "get_realtime_snapshot": {
            "func": get_realtime_snapshot,
            "schema": RealtimeIn,
            "description": "获取股票实时快照（现价、涨跌幅、成交额、换手率）。输入：股票代码。",
        },
        "get_drawings": {
            "func": get_drawings,
            "schema": DrawingsIn,
            "description": "读取用户在 K线图上绘制的标注（趋势线/水平线/斐波那契回撤/矩形区间）及其日期与价格。输入：股票代码。",
        },
        "run_screener": {
            "func": _run_screener_lazy,
            "schema": ScreenerIn,
            "description": "按结构化条件筛选股票（市场/板块/价格区间/涨跌幅区间）。输入：可选条件。",
        },
    }


def _run_screener_lazy(code: str = "", market: str | None = None,
                       board: str | None = None, price_min: float | None = None,
                       price_max: float | None = None, chg_min: float | None = None,
                       chg_max: float | None = None, limit: int = 20,
                       **_) -> ToolResult:
    """Screener 延迟接入（模块四实现后启用）。"""
    try:
        from core.screener import run_screener as _rs
        data = _rs(market=market, board=board, price_min=price_min,
                   price_max=price_max, chg_min=chg_min, chg_max=chg_max, limit=limit)
        return ok_result("run_screener", data, data.get("note", ""))
    except Exception as e:  # noqa: BLE001
        return fail_result("run_screener", f"筛选引擎未就绪：{e}")


def call_tool(name: str, kwargs: dict) -> ToolResult:
    """按名称调用工具（AgentCore / MCP 共用入口）。"""
    reg = build_registry()
    entry = reg.get(name)
    if not entry:
        return fail_result(name, f"工具不存在：{name}")
    func = entry["func"]
    try:
        # Pydantic 校验入参（类型安全）；model_dump() 保留默认值字段
        schema = entry["schema"]
        if schema is not None and kwargs:
            kwargs = schema(**kwargs).model_dump()
        return func(**kwargs)
    except Exception as e:  # noqa: BLE001
        log.exception("工具 %s 调用异常", name)
        return fail_result(name, f"{type(e).__name__}: {e}")
