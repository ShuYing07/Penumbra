# -*- coding: utf-8 -*-
"""决策反思：到期决策对照实际收益 → 落反思 → 注入后续分析 → 胜率统计。

纪律：评估只使用"当下已可得"的行情（决策日+N个交易日的收盘价），
不存在前视偏差——回看是现在做的，不是决策时假装知道未来。
"""
from __future__ import annotations

import json
import logging

from core.config import now_cn
from core.data import cache, service
from core.data.cache import get_conn

log = logging.getLogger("stockai.reflect")

HOLD_BARS_DEFAULT = 10  # 决策后 10 个交易日评估（约两周）

_BUY = ("买入", "强烈买入")
_SELL = ("卖出",)


def evaluate_pending(limit: int = 20) -> list[dict]:
    """评估所有未评估且数据已足够的决策；返回本次完成评估的列表。"""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT id, ticker, action, price, asof, trader, summary FROM decisions
               WHERE evaluated=0 ORDER BY id ASC LIMIT ?""", (limit,)).fetchall()

    done: list[dict] = []
    for did, ticker, action, price, asof, trader_json, summary in rows:
        try:
            ret = _realized_return(ticker, asof or "", float(price or 0))
        except Exception as e:  # noqa: BLE001
            log.debug("决策 %s 评估跳过：%s", did, e)
            continue
        if ret is None:
            continue  # 到期交易日数据尚不足
        direction = 1 if action in _BUY else (-1 if action in _SELL else 0)
        aligned = (direction * ret > 0) if direction else None
        text = (f"建议「{action}」，{HOLD_BARS_DEFAULT}个交易日后实际涨跌 {ret * 100:+.2f}%，"
                + ("方向一致。" if aligned else ("方向相反，需警惕同类误判。" if aligned is False
                                              else "该建议为观望，仅作记录。")))
        with get_conn() as conn:
            conn.execute(
                """UPDATE decisions SET evaluated=1, realized_return_pct=?, reflection=?, ts_reflected=?
                   WHERE id=?""",
                (round(ret * 100, 3), text, now_cn().isoformat(timespec="seconds"), did))
        # 蒸馏偏好标注（good/bad/neutral + 实际收益），失败不阻塞
        try:
            from core.training import distill

            distill.record_preference(
                decision_id=did, ticker=ticker, action=action,
                trader_output=trader_json or "",
                instruction=(f"作为交易员对 {ticker} 给出操作决策。当时结论摘要："
                             f"{summary or ''}。请输出包含 action/position_pct/reasoning 的 JSON。"),
                realized_return_pct=round(ret * 100, 3), aligned=aligned)
        except Exception:  # noqa: BLE001
            pass
        done.append({"id": did, "ticker": ticker, "action": action,
                     "realized_return_pct": round(ret * 100, 3), "reflection": text})
    if done:
        log.info("决策反思完成 %d 条：%s", len(done), [d["id"] for d in done])
    return done


def _realized_return(ticker: str, asof: str, price: float) -> float | None:
    """决策日+N交易日收盘价相对决策价的涨跌；数据不足返回 None。"""
    if price <= 0 or not asof:
        return None
    bars, _ = service.get_daily(ticker)
    if bars is None or len(bars) == 0:
        return None
    idx = bars.index.searchsorted(asof)
    if idx >= len(bars):  # 决策日无行情（非交易日按其后首个交易日）
        idx = min(idx, len(bars) - 1)
    eval_idx = idx + HOLD_BARS_DEFAULT
    if eval_idx >= len(bars):
        return None
    base_close = float(bars["close"].iloc[idx])
    eval_close = float(bars["close"].iloc[eval_idx])
    if base_close <= 0:
        return None
    # 用决策日收盘修正基准更公平（决策时参考价=实时价，评估锚定同源收盘）
    return eval_close / base_close - 1


def inject_context(ticker: str, limit: int = 5) -> list[dict]:
    """取该标的最近的已评估决策，供交易员/风控 prompt 参考。"""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT ts, action, price, realized_return_pct, reflection FROM decisions
               WHERE ticker=? AND evaluated=1 ORDER BY id DESC LIMIT ?""",
            (ticker.upper(), limit)).fetchall()
    return [{"时间": r[0][:10], "建议": r[1], "当时价": r[2],
             "实际涨跌%": r[3], "反思": r[4]} for r in rows]


def decision_stats() -> dict:
    """复盘统计：全部/已评估/方向一致率/平均实际收益/最佳最差。"""
    with get_conn() as conn:
        row = conn.execute(
            """SELECT COUNT(*), SUM(evaluated),
                      SUM(CASE WHEN evaluated=1 AND action IN ('买入','强烈买入')
                                AND realized_return_pct>0 THEN 1 ELSE 0 END),
                      SUM(CASE WHEN evaluated=1 AND action IN ('卖出')
                                AND realized_return_pct<0 THEN 1 ELSE 0 END),
                      AVG(CASE WHEN evaluated=1 THEN realized_return_pct END),
                      MAX(CASE WHEN evaluated=1 THEN realized_return_pct END),
                      MIN(CASE WHEN evaluated=1 THEN realized_return_pct END)
               FROM decisions""").fetchone()
    total, evaluated, buy_win, sell_win, avg_ret, best, worst = row
    evaluated = evaluated or 0
    directional = (buy_win or 0) + (sell_win or 0)
    return {
        "total": total or 0, "evaluated": evaluated,
        "directional_right": directional,
        "win_rate_pct": round(directional / evaluated * 100, 1) if evaluated else None,
        "avg_return_pct": round(avg_ret, 2) if avg_ret is not None else None,
        "best_pct": round(best, 2) if best is not None else None,
        "worst_pct": round(worst, 2) if worst is not None else None,
    }


def history_lines(ticker: str, limit: int = 5) -> str:
    """把反思上下文压成多行文本（写日志用）。"""
    items = inject_context(ticker, limit)
    return "\n".join(json.dumps(x, ensure_ascii=False) for x in items)
