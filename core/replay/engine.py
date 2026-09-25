# -*- coding: utf-8 -*-
"""回放调度：历史选点 → 时点切片跑 AI 管线 → t+N 真实走势评估 → 统计。

纪律：
- 选点时间基准只来自 bars 实际交易日索引（不用系统时间，不伪造）；
- 每点 run_analysis(as_of=..., persist=False)，信号入独立表，不碰 decisions/RAG；
- 单点失败记 error 行不中断批次；数据不足的点不评估（ret=NULL）。
"""
from __future__ import annotations

import logging

from core.config import now_cn
from core.data import service
from core.llm import LLMRunner
from core.replay import store

log = logging.getLogger("stockai.replay")

HORIZONS = (5, 10, 20)
_LONG = ("买入", "强烈买入", "加仓")
_SHORT = ("卖出", "回避", "减仓")


# ---------- 选点 ----------
def pick_dates(bars, start: str | None = None, end: str | None = None,
               step_bars: int = 20, min_warmup: int = 120,
               min_forward: int = 20) -> list[str]:
    """从实际交易日索引生成回放点。

    - start/end 限定回放决策日区间（字符串 YYYY-MM-DD，非交易日自然落到其后首日）；
    - 首个候选点前须有 ≥min_warmup 根（保证 MA60/MACD 等指标有效）；
    - 每 step_bars 个交易日一点；末点距数据末尾须 ≥min_forward（保证20日评估有答案）；
    - 合格点不足 2 个抛 ValueError（不静默、不伪造）。
    """
    idx = bars.index
    lo = idx.searchsorted(start or idx[0], side="left") if start else 0
    hi = idx.searchsorted(end or idx[-1], side="right") if end else len(idx)
    # 末点后还要留 min_forward 根
    last_ok = min(hi, len(idx) - min_forward)
    first = max(lo, min_warmup)
    if last_ok - first < step_bars:
        raise ValueError(
            f"区间内可回放点不足：首点位置{first}、末点位置{last_ok}、"
            f"步长{step_bars}（请扩大起止区间或减小步长/warmup）")
    positions = list(range(first, last_ok, step_bars))
    return [idx[p].strftime("%Y-%m-%d") for p in positions]


def _direction(action: str) -> int:
    """+1 多 / -1 空 / 0 中性。"""
    if action in _LONG:
        return 1
    if action in _SHORT:
        return -1
    return 0


def _make_runner(engine: str) -> LLMRunner:
    engine = (engine or "mock").lower()
    if engine == "mock":
        return LLMRunner(mock=True)
    if engine in ("deepseek", "local"):
        return LLMRunner(mock=False, backend=engine)
    raise ValueError(f"未知回放引擎: {engine}（支持 mock/deepseek/local）")


# ---------- 批量回放 ----------
def run_replay(ticker: str, start: str | None = None, end: str | None = None,
               step_bars: int = 20, engine: str = "mock",
               progress_cb=None) -> str:
    """批量历史回放，返回 batch_id。跑完自动评估。"""
    ticker = ticker.upper()
    bars, _ = service.get_daily(ticker)
    if bars is None or len(bars) == 0:
        raise ValueError(f"无行情数据: {ticker}")
    dates = pick_dates(bars, start, end, step_bars)
    market = service.market_of(ticker)
    batch_id = f"{ticker}_{(engine or 'mock').lower()}_{now_cn():%Y%m%d%H%M%S}"
    runner = _make_runner(engine)
    engine_label = engine if engine != "mock" else "mock(规则桩)"

    total = len(dates)
    for n, asof in enumerate(dates, 1):
        msg = f"[{n}/{total}] {ticker} 回放 {asof}"
        log.info(msg)
        if progress_cb:
            try:
                progress_cb(n, total, asof)
            except Exception:  # noqa: BLE001
                pass
        try:
            res = run_one(ticker, asof, runner)
            store.save_signal(batch_id, ticker, market, engine_label,
                              asof, res)
        except Exception as e:  # noqa: BLE001
            log.warning("回放点失败 %s %s: %s", ticker, asof, e)
            store.save_signal(batch_id, ticker, market, engine_label, asof,
                              {}, error=f"{type(e).__name__}: {e}")
    evaluate_batch(batch_id, bars)
    return batch_id


def run_one(ticker: str, as_of: str, runner: LLMRunner | None = None) -> dict:
    """单个历史时点跑一次管线（不持久化到 decisions/RAG），返回 final 决策 dict。"""
    from core.agents.graph import run_analysis

    res = run_analysis(ticker, runner=runner, as_of=as_of, persist=False)
    final = (res.get("state") or {}).get("final") or {}
    if not final:
        raise RuntimeError("管线未产出 final 决策")
    return final


# ---------- 评估 ----------
def evaluate_batch(batch_id: str, bars=None) -> int:
    """用全量 bars 计算批次内每条信号 t+5/10/20 真实收益与方向命中。返回评估条数。"""
    rows = [r for r in store.list_batch(batch_id) if not r["evaluated"] and not r["error"]]
    if not rows:
        return 0
    if bars is None:
        bars, _ = service.get_daily(rows[0]["ticker"])
    closes = bars["close"]
    idx = bars.index
    done = 0
    for r in rows:
        pos = idx.searchsorted(r["asof"], side="left")
        if pos >= len(idx) or idx[pos].strftime("%Y-%m-%d") != r["asof"]:
            continue  # 决策日不在交易日索引（理论上不会，选点来自索引）
        base = float(closes.iloc[pos])
        if base <= 0:
            continue
        rets, hits = {}, {}
        for h in HORIZONS:
            if pos + h >= len(closes):
                continue
            ret = float(closes.iloc[pos + h]) / base - 1
            rets[h] = round(ret * 100, 3)
            d = _direction(r["action"] or "")
            hits[h] = (1 if d * ret > 0 else 0) if d else None
        if rets:
            store.update_evaluation(r["id"], rets, hits)
            done += 1
    return done


# ---------- 统计 ----------
def batch_stats(batch_id: str) -> dict:
    """批次汇总：信号分布 + 各 horizon 方向胜率/平均收益（多空分列）。"""
    rows = store.list_batch(batch_id)
    n = len(rows)
    dist = {"多": 0, "空": 0, "中性": 0, "错误": 0}
    for r in rows:
        if r["error"]:
            dist["错误"] += 1
        else:
            d = _direction(r["action"] or "")
            dist["多" if d > 0 else ("空" if d < 0 else "中性")] += 1

    horizons_stat = {}
    for h in HORIZONS:
        rc, rh = f"ret_{h}", f"hit_{h}"
        evals = [r for r in rows if r["evaluated"] and r[rc] is not None]
        directional = [r for r in evals if r[rh] in (0, 1)]
        longs = [r for r in directional if _direction(r["action"] or "") > 0]
        shorts = [r for r in directional if _direction(r["action"] or "") < 0]
        wins = sum(1 for r in directional if r[rh] == 1)

        def avg(items):
            return round(sum(float(r[rc]) for r in items) / len(items), 2) if items else None

        horizons_stat[h] = {
            "evaluated": len(evals),
            "directional": len(directional),
            "win_rate_pct": round(wins / len(directional) * 100, 1) if directional else None,
            "avg_ret_pct": avg(evals),
            "long_n": len(longs), "long_avg_pct": avg(longs),
            "short_n": len(shorts), "short_avg_pct": avg(shorts),
        }
    return {"batch_id": batch_id, "n": n, "distribution": dist,
            "horizons": horizons_stat}
