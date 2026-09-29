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
    """A股全量实时快照 [{code,name,price,chg_pct,industry}]，5 分钟缓存。"""
    def _load():
        from core.config import domestic_network
        import akshare as ak
        with domestic_network():
            df = ak.stock_zh_a_spot_em()
        out = []
        for _, r in df.iterrows():
            try:
                out.append({
                    "code": str(r["代码"]),
                    "name": str(r["名称"]),
                    "price": float(r.get("最新价", 0) or 0),
                    "chg_pct": float(r.get("涨跌幅", 0) or 0),
                    "industry": str(r.get("所属行业", "")),
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
                 limit: int = 20) -> dict:
    """按结构化条件筛选股票。返回 {ok, hits:[{code,name,market,price,chg_pct,board}], note}。"""
    index = _index()
    pool = index
    notes: list[str] = []

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

    # 3) 实时快照（价格/涨跌幅）——仅 A股可精确筛选
    price_supported = market in (None, "A股", "全部")
    snap: Dict[str, dict] = {}
    if price_supported and (price_min is not None or price_max is not None
                            or chg_min is not None or chg_max is not None):
        spot = _a_spot()
        if spot:
            snap = {s["code"]: s for s in spot}
        else:
            notes.append("A股实时快照不可达，价格/涨跌幅条件仅做代码级过滤")

    hits: List[dict] = []
    for s in pool:
        code = s["code"]
        price = snap.get(code, {}).get("price")
        chg = snap.get(code, {}).get("chg_pct")
        if price is not None:
            if price_min is not None and price < price_min:
                continue
            if price_max is not None and price > price_max:
                continue
        elif price_min is not None or price_max is not None:
            if market not in (None, "A股", "全部"):
                continue  # 非 A股且无实时 → 无法满足价格条件，剔除
        if chg is not None:
            if chg_min is not None and chg < chg_min:
                continue
            if chg_max is not None and chg > chg_max:
                continue
        elif chg_min is not None or chg_max is not None:
            if market not in (None, "A股", "全部"):
                continue
        hits.append({"code": s["code"], "name": s["name"], "market": s["market"],
                     "price": price, "chg_pct": chg, "board": s.get("board", "")})
        if len(hits) >= limit:
            break

    note = "；".join(notes) or "筛选完成"
    if not notes and not snap and any(
            v is not None for v in (price_min, price_max, chg_min, chg_max)):
        note = "仅按索引代码级筛选（未附加实时条件）"
    return {"ok": True, "hits": hits, "note": note, "total": len(hits)}
