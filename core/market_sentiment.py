# -*- coding: utf-8 -*-
"""市场情绪面板（模块七 · 参考九章·ALGOR 恐惧贪婪/五维情绪/世界指数）。

- fear_greed_index(stats)：恐惧贪婪指数 0~100（极度恐惧=0 → 极度贪婪=100），
  由涨跌家数、量能、北向资金、波动率、换手五维加权合成；
- five_dimension_sentiment(stats)：五维情绪（每维 -100~100，正=乐观）；
- global_indices(fetch=True)：全球主要指数清单，在线实时获取失败时
  降级为静态参考值并标记 stale（「数据可能延迟」）。

全部确定性规则；输入缺失维度按中性处理并计数，绝不因数据不全而报错。
market_stats 字段（均可缺省）：
    advancers/decliners 涨跌家数、volume_ratio 量比、north_flow_bn 北向资金(亿)、
    volatility_20 20日波动率、turnover_rate 换手率(%)。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

log = logging.getLogger("stockai.core.market_sentiment")

# 全球主要指数静态表（在线失败时的降级参考值；实时时以行情源为准）
GLOBAL_INDICES: List[Dict[str, Any]] = [
    {"code": "000001", "name": "上证指数", "market": "A股", "last": 3350.12, "change_pct": 0.42},
    {"code": "399001", "name": "深证成指", "market": "A股", "last": 10650.30, "change_pct": 0.61},
    {"code": "399006", "name": "创业板指", "market": "A股", "last": 2210.45, "change_pct": 0.88},
    {"code": "000300", "name": "沪深300", "market": "A股", "last": 3920.77, "change_pct": 0.35},
    {"code": "000905", "name": "中证500", "market": "A股", "last": 5812.40, "change_pct": 0.52},
    {"code": "HSI", "name": "恒生指数", "market": "港股", "last": 22140.55, "change_pct": -0.18},
    {"code": "HSTECH", "name": "恒生科技", "market": "港股", "last": 5120.30, "change_pct": 0.75},
    {"code": "DJI", "name": "道琼斯", "market": "美股", "last": 43510.60, "change_pct": 0.24},
    {"code": "SPX", "name": "标普500", "market": "美股", "last": 5952.15, "change_pct": 0.31},
    {"code": "IXIC", "name": "纳斯达克", "market": "美股", "last": 19880.90, "change_pct": 0.55},
    {"code": "N225", "name": "日经225", "market": "亚太", "last": 40230.10, "change_pct": 0.42},
    {"code": "KS11", "name": "韩国KOSPI", "market": "亚太", "last": 2780.30, "change_pct": -0.15},
    {"code": "TWII", "name": "台湾加权", "market": "亚太", "last": 22980.40, "change_pct": 0.38},
    {"code": "FTSE", "name": "英国富时100", "market": "欧洲", "last": 8310.25, "change_pct": -0.10},
    {"code": "DAX", "name": "德国DAX", "market": "欧洲", "last": 19920.80, "change_pct": 0.22},
    {"code": "CAC", "name": "法国CAC40", "market": "欧洲", "last": 7690.15, "change_pct": 0.12},
    {"code": "STOXX50", "name": "欧洲斯托克50", "market": "欧洲", "last": 5010.60, "change_pct": 0.18},
    {"code": "SENSEX", "name": "印度SENSEX", "market": "新兴", "last": 82150.30, "change_pct": 0.66},
    {"code": "IBOV", "name": "巴西IBOVESPA", "market": "新兴", "last": 128700.90, "change_pct": -0.24},
    {"code": "ASX200", "name": "澳洲ASX200", "market": "亚太", "last": 8440.20, "change_pct": 0.29},
]


def _clip(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def fear_greed_index(stats: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """恐惧贪婪指数 0~100（0=极度恐惧，50=中性，100=极度贪婪）。"""
    s = dict(stats or {})
    used, parts = 0, []
    adv = float(s.get("advancers") or 0)
    dec = float(s.get("decliners") or 0)
    if adv + dec > 0:
        used += 1
        parts.append(50.0 + 100.0 * (adv / (adv + dec) - 0.5))
    vr = float(s.get("volume_ratio") or 0)
    if vr > 0:
        used += 1
        parts.append(50.0 + 50.0 * (vr - 1.0))
    nf = float(s.get("north_flow_bn") or 0)
    if s.get("north_flow_bn") is not None or nf != 0:
        used += 1
        parts.append(50.0 + nf / 20.0 * 50.0)
    vol = float(s.get("volatility_20") or 0)
    if vol > 0:
        used += 1
        parts.append(50.0 - (vol - 0.01) / 0.02 * 50.0)
    tr = float(s.get("turnover_rate") or 0)
    if tr > 0:
        used += 1
        parts.append(50.0 + 30.0 * (tr - 1.0))
    if not parts:
        return {"index": 50.0, "level": "中性", "dimensions_used": 0,
                "note": "市场统计数据不足，按中性 50 处理"}
    idx = _clip(sum(parts) / len(parts))
    level = ("极度贪婪" if idx >= 80 else "贪婪" if idx >= 65
             else "中性偏贪婪" if idx >= 55
             else "中性" if idx >= 45
             else "中性偏恐惧" if idx >= 35
             else "恐惧" if idx >= 20 else "极度恐惧")
    return {"index": round(idx, 1), "level": level,
            "dimensions_used": used, "note": ""}


def five_dimension_sentiment(stats: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """五维市场情绪：每维 -100~100（正=乐观），返回 {dimensions, avg, note}。"""
    s = dict(stats or {})
    dims: Dict[str, float] = {}
    adv = float(s.get("advancers") or 0)
    dec = float(s.get("decliners") or 0)
    if adv + dec > 0:
        dims["涨跌家数"] = _clip(200.0 * (adv / (adv + dec) - 0.5), -100, 100)
    vr = float(s.get("volume_ratio") or 0)
    if vr > 0:
        dims["量能"] = _clip(200.0 * (vr - 1.0), -100, 100)
    if s.get("north_flow_bn") is not None:
        dims["北向资金"] = _clip(float(s["north_flow_bn"]) / 20.0 * 100.0, -100, 100)
    vol = float(s.get("volatility_20") or 0)
    if vol > 0:
        dims["波动率"] = _clip(-100.0 * (vol - 0.01) / 0.01, -100, 100)
    tr = float(s.get("turnover_rate") or 0)
    if tr > 0:
        dims["换手率"] = _clip(200.0 * (tr - 1.0), -100, 100)
    avg = round(sum(dims.values()) / len(dims), 1) if dims else 0.0
    return {"dimensions": dims, "avg": avg,
            "note": "" if len(dims) == 5 else
            f"数据不完整（{len(dims)}/5 维），缺失维度按 0 处理"}


def global_indices(fetch: bool = True) -> Dict[str, Any]:
    """全球主要指数（红涨绿跌惯例由 UI 侧按 change_pct 渲染）。

    在线获取成功 → {rows, stale=False, source}；
    失败/离线 → 静态参考值 + stale=True（「数据可能延迟」）。
    """
    rows = [dict(r) for r in GLOBAL_INDICES]
    if not fetch:
        return {"rows": rows, "stale": True, "source": "static",
                "note": "离线模式：显示静态参考值，数据可能延迟"}
    try:
        import akshare as ak
        df = ak.index_global_spot_em()  # 东方财富全球指数实时
        if df is not None and not df.empty:
            code_col = next((c for c in ("代码", "code") if c in df.columns), None)
            name_col = next((c for c in ("名称", "name") if c in df.columns), None)
            last_col = next((c for c in ("最新价", "last") if c in df.columns), None)
            pct_col = next((c for c in ("涨跌幅", "change_pct", "涨跌幅(%)")
                            if c in df.columns), None)
            live = []
            for _, r in df.iterrows():
                live.append({
                    "code": str(r.get(code_col, "")) if code_col else "",
                    "name": str(r.get(name_col, "")) if name_col else "",
                    "market": "全球", "last": float(r.get(last_col, 0) or 0),
                    "change_pct": float(r.get(pct_col, 0) or 0),
                })
            if live:
                return {"rows": live, "stale": False, "source": "akshare",
                        "note": "实时行情"}
    except Exception as e:  # noqa: BLE001
        log.warning("global_indices 在线获取失败，降级静态: %s", e)
    return {"rows": rows, "stale": True, "source": "static",
            "note": "实时获取失败，显示静态参考值，数据可能延迟"}


if __name__ == "__main__":
    stats = {"advancers": 3200, "decliners": 1200, "volume_ratio": 1.25,
             "north_flow_bn": 18.5, "volatility_20": 0.015, "turnover_rate": 1.6}
    fg = fear_greed_index(stats)
    assert 0 <= fg["index"] <= 100 and fg["dimensions_used"] == 5
    five = five_dimension_sentiment(stats)
    assert len(five["dimensions"]) == 5 and all(-100 <= v <= 100
                                               for v in five["dimensions"].values())
    # 空数据不报错
    fg0 = fear_greed_index({})
    assert fg0["index"] == 50.0 and fg0["dimensions_used"] == 0
    five0 = five_dimension_sentiment({})
    assert five0["avg"] == 0.0
    # 部分数据
    fg1 = fear_greed_index({"advancers": 100, "decliners": 100})
    assert fg1["index"] == 50.0 and fg1["dimensions_used"] == 1
    # 全球指数离线降级
    gi = global_indices(fetch=False)
    assert gi["stale"] is True and len(gi["rows"]) >= 15
    print(f"market_sentiment self-check ok (fg={fg['index']} "
          f"{fg['level']}, five_avg={five['avg']}, indices={len(gi['rows'])})")
