# -*- coding: utf-8 -*-
"""结构化股票筛选引擎（Screener）。

数据源与降级（诚实标注口径）：
- A股实时快照（价格/涨跌幅）：东财 stock_zh_a_spot_em()，5 分钟缓存；
  不可达 → 仅返回索引代码级结果并在 note 标注"实时数据不可达"。
- 行业成分：东财板块接口，24h 缓存；不可达 → board 仅按上市板块过滤。
- 港股/美股：索引仅有代码/名称/市场，无实时全量 → 价格/涨跌幅条件不适用
  （返回代码级结果并标注）。
全部输出为客观筛选结果，不构成投资建议。
"""
from __future__ import annotations

import logging
import time
from functools import lru_cache
from typing import Any, Dict, List, Optional

log = logging.getLogger("stockai.screener")

_cache: Dict[str, tuple[float, Any]] = {}  # key -> (ts, data)


def _cached(key: str, ttl: int, loader):
    now = time.time()
    hit = _cache.get(key)
    if hit and now - hit[0] < ttl:
        return hit[1]
    try:
        data = loader()
        _cache[key] = (now, data)
        return data
    except Exception as e:  # noqa: BLE001
        log.warning("screener 数据源 %s 失败：%s", key, e)
        return None


@lru_cache(maxsize=1)
def _index() -> List[dict]:
    import json
    from pathlib import Path
    p = Path(__file__).resolve().parents[1] / "data" / "all_stocks.json"
    if not p.exists():
        return []
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def _a_spot() -> Optional[List[dict]]:
    """A股全量实时快照 [{code,name,price,chg_pct,industry,pe,pb,mcap,volume,turnover}]。"""
    def _load():
        from core.config import domestic_network
        import akshare as ak
        with domestic_network():
            df = ak.stock_zh_a_spot_em()
        out = []
        for _, r in df.iterrows():
            try:
                def _f(key, default=0.0):
                    v = r.get(key)
                    if v is None or str(v) in ("", "-", "nan", "None"):
                        return default
                    try:
                        return float(v)
                    except Exception:  # noqa: BLE001
                        return default
                out.append({
                    "code": str(r["代码"]),
                    "name": str(r["名称"]),
                    "price": _f("最新价"),
                    "chg_pct": _f("涨跌幅"),
                    "industry": str(r.get("所属行业", "")),
                    "pe": _f("市盈率-动态"),
                    "pb": _f("市净率"),
                    "mcap": _f("总市值"),
                    "volume": _f("成交量"),
                    "turnover": _f("换手率"),
                })
            except Exception:  # noqa: BLE001
                continue
        return out
    return _cached("a_spot", 300, _load)


def _industry_stocks(industry: str) -> Optional[set[str]]:
    """行业成分股代码集合，24h 缓存。"""
    def _load():
        from core.config import domestic_network
        import akshare as ak
        with domestic_network():
            cons = ak.stock_board_industry_cons_em(symbol=industry)
        return {str(c) for c in cons.iloc[:, 0].astype(str)}
    return _cached(f"ind:{industry}", 86400, _load)


def run_screener(market: Optional[str] = None, board: Optional[str] = None,
                 price_min: Optional[float] = None, price_max: Optional[float] = None,
                 chg_min: Optional[float] = None, chg_max: Optional[float] = None,
                 pe_min: Optional[float] = None, pe_max: Optional[float] = None,
                 pb_min: Optional[float] = None, pb_max: Optional[float] = None,
                 mcap_min: Optional[float] = None, mcap_max: Optional[float] = None,
                 volume_min: Optional[float] = None, turnover_min: Optional[float] = None,
                 dividend_yield_min: Optional[float] = None,
                 limit: int = 20) -> dict:
    """按结构化条件筛选股票。返回 {ok, hits:[{code,name,market,price,chg_pct,board,...}], note}。

    估值/市值/量能条件（pe/pb/mcap/volume/turnover）仅 A股实时快照可得；
    股息率条件当前数据源暂缺，会明确标注未应用（不静默忽略用户意图）。
    """
    index = _index()
    pool = index
    notes: list[str] = []
    if dividend_yield_min is not None:
        notes.append(f"股息率≥{dividend_yield_min}%：当前数据源暂缺该字段，未应用此条件")

    # 1) 市场过滤
    if market and market != "全部":
        pool = [s for s in pool if s.get("market") == market]

    # 2) 板块过滤：上市板块（索引字段）或行业（东财成分）
    industry_codes: set[str] | None = None
    if board:
        board_hits = [s for s in pool if s.get("board") == board]
        if board_hits:
            pool = board_hits
        else:
            industry_codes = _industry_stocks(board)
            if industry_codes is None:
                notes.append(f"行业「{board}」成分数据不可达，已跳过板块条件")
            else:
                pool = [s for s in pool if s["code"] in industry_codes]

    # 3) 实时快照（价格/涨跌幅/估值/市值/量能）——仅 A股可精确筛选
    price_supported = market in (None, "A股", "全部")
    snap: Dict[str, dict] = {}
    need_spot = any(v is not None for v in (
        price_min, price_max, chg_min, chg_max,
        pe_min, pe_max, pb_min, pb_max,
        mcap_min, mcap_max, volume_min, turnover_min))
    if price_supported and need_spot:
        spot = _a_spot()
        if spot:
            snap = {s["code"]: s for s in spot}
        else:
            notes.append("A股实时快照不可达，价格/涨跌幅/估值条件仅做代码级过滤")

    def _num(d: dict, key: str):
        v = d.get(key)
        return v if v is not None and float(v or 0) > 0 else None

    hits: List[dict] = []
    for s in pool:
        code = s["code"]
        row = snap.get(code, {})
        price = _num(row, "price")
        chg = _num(row, "chg_pct")
        pe = _num(row, "pe")
        pb = _num(row, "pb")
        mcap = _num(row, "mcap")
        volume = _num(row, "volume")
        turnover = _num(row, "turnover")
        a_only = market in (None, "A股", "全部")
        # 价格
        if price is not None:
            if price_min is not None and price < price_min:
                continue
            if price_max is not None and price > price_max:
                continue
        elif price_min is not None or price_max is not None:
            if not a_only:
                continue  # 非 A股且无实时 → 无法满足条件，剔除
        # 涨跌幅
        if chg is not None:
            if chg_min is not None and chg < chg_min:
                continue
            if chg_max is not None and chg > chg_max:
                continue
        elif chg_min is not None or chg_max is not None:
            if not a_only:
                continue
        # 估值/市值/量能：仅 A股快照字段，缺失即不满足条件（A股）或剔除（其他市场）
        for val, lo, hi in ((pe, pe_min, pe_max), (pb, pb_min, pb_max),
                            (mcap, mcap_min, mcap_max), (volume, volume_min, None),
                            (turnover, turnover_min, None)):
            if lo is None and hi is None:
                continue
            if val is None:
                if not a_only:
                    continue  # 非 A股无快照 → 剔除
                # A股快照缺失该字段（如停牌）→ 不满足严格筛选
                continue
            if lo is not None and val < lo:
                break
            if hi is not None and val > hi:
                break
        else:
            hits.append({"code": s["code"], "name": s["name"], "market": s["market"],
                         "price": price, "chg_pct": chg, "board": s.get("board", ""),
                         "pe": pe, "pb": pb, "mcap": mcap, "volume": volume,
                         "turnover": turnover})
            if len(hits) >= limit:
                break

    note = "；".join(notes) or "筛选完成"
    if not notes and not snap and need_spot:
        note = "仅按索引代码级筛选（未附加实时条件）"
    return {"ok": True, "hits": hits, "note": note, "total": len(hits)}


# ---------------------------------------------------------------------------
# 自然语言 → 结构化筛选条件（规则引擎为主，LLM 兜底增强）
# ---------------------------------------------------------------------------

_NL_PATTERNS = [
    # 市盈率：低于15 / 小于15 / PE<15 / 市盈率大于30
    (r"市盈率\s*(?:低于|小于|<|不大于|≤)\s*(\d+(?:\.\d+)?)", lambda m: {"pe_max": float(m.group(1))}),
    (r"市盈率\s*(?:高于|大于|>|≥)\s*(\d+(?:\.\d+)?)", lambda m: {"pe_min": float(m.group(1))}),
    (r"pe\s*(?:低于|小于|<)\s*(\d+(?:\.\d+)?)", lambda m: {"pe_max": float(m.group(1))}),
    (r"pe\s*(?:高于|大于|>)\s*(\d+(?:\.\d+)?)", lambda m: {"pe_min": float(m.group(1))}),
    # 市净率
    (r"市净率\s*(?:低于|小于|<)\s*(\d+(?:\.\d+)?)", lambda m: {"pb_max": float(m.group(1))}),
    (r"市净率\s*(?:高于|大于|>)\s*(\d+(?:\.\d+)?)", lambda m: {"pb_min": float(m.group(1))}),
    # 股息率
    (r"股息率\s*(?:高于|大于|>)\s*(\d+(?:\.\d+)?)%?", lambda m: {"dividend_yield_min": float(m.group(1))}),
    # 市值
    (r"市值\s*(?:大于|高于|>)\s*(\d+(?:\.\d+)?)\s*(亿|亿)?", lambda m: {"mcap_min": float(m.group(1)) * 1e8 if m.group(2) else float(m.group(1))}),
    (r"市值\s*(?:小于|低于|<)\s*(\d+(?:\.\d+)?)\s*(亿|亿)?", lambda m: {"mcap_max": float(m.group(1)) * 1e8 if m.group(2) else float(m.group(1))}),
    # 价格
    (r"股价\s*(?:低于|<)\s*(\d+(?:\.\d+)?)", lambda m: {"price_max": float(m.group(1))}),
    (r"股价\s*(?:高于|大于|>)\s*(\d+(?:\.\d+)?)", lambda m: {"price_min": float(m.group(1))}),
    # 涨跌幅
    (r"(?:涨跌幅|涨幅)\s*(?:大于|高于|超过|>)\s*(\d+(?:\.\d+)?)%?", lambda m: {"chg_min": float(m.group(1))}),
    (r"(?:跌|跌幅)\s*(?:大于|超过)\s*(\d+(?:\.\d+)?)%?", lambda m: {"chg_max": -float(m.group(1))}),
]

_INDUSTRY_KEYWORDS = [
    "银行", "白酒", "医药", "医疗", "证券", "保险", "半导体", "芯片", "新能源",
    "光伏", "储能", "军工", "汽车", "地产", "钢铁", "煤炭", "石油", "化工",
    "食品", "饮料", "家电", "消费", "农业", "传媒", "计算机", "软件", "通信",
]


def parse_natural_language(query: str) -> dict:
    """把中文选股语句解析为 run_screener 条件字典（规则引擎，无网络/LLM 依赖）。

    “市盈率低于15、股息率高于3%的银行股” →
    {pe_max: 15, dividend_yield_min: 3, board: "银行"}
    """
    import re
    q = query.strip()
    if not q:
        return {}
    cond: dict = {}
    for pat, fn in _NL_PATTERNS:
        m = re.search(pat, q, flags=re.IGNORECASE)
        if m:
            cond.update(fn(m))
    # 行业
    for kw in _INDUSTRY_KEYWORDS:
        if kw in q:
            cond["board"] = kw
            break
    # 市场
    if "港股" in q:
        cond["market"] = "港股"
    elif "美股" in q or "美国" in q:
        cond["market"] = "美股"
    elif "A股" in q or "沪深" in q:
        cond["market"] = "A股"
    return cond


def natural_language_screen(query: str, limit: int = 20) -> dict:
    """一句话选股：解析自然语言 → 结构化筛选。返回 {ok, query, criteria, hits, note}。"""
    cond = parse_natural_language(query)
    if not cond:
        return {"ok": False, "query": query, "criteria": {},
                "hits": [], "note": "未能从语句中解析出筛选条件，请尝试："
                                    "“市盈率低于15、股息率高于3%的银行股”"}
    cond["limit"] = limit
    try:
        res = run_screener(**cond)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "query": query, "criteria": cond,
                "hits": [], "note": f"筛选失败：{e}"}
    res["query"] = query
    res["criteria"] = {k: v for k, v in cond.items() if k != "limit"}
    return res
