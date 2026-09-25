# -*- coding: utf-8 -*-
"""盯盘调度核心：批量取数 + 算指标快照 + 逐条评估 + 错误隔离。

scan_all() 被 UI 的 QTimer 后台线程调用，也供未来 CLI 复用。
单只取数/评估异常 → 该行 status=—无数据，继续下一只，绝不拖垮整轮。
触发后写 last_trigger_at，STOCKAI_RETRIGGER_MIN（默认 60 分钟）内不重弹。
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta

from core.config import now_cn
from core.data import service
from core.quant.indicators import latest_snapshot
from core.watchlist import conditions, store

log = logging.getLogger("stockai.watchlist")

RETRIGGER_MIN = int(os.environ.get("STOCKAI_RETRIGGER_MIN", "60"))


@dataclass
class ScanRow:
    ticker: str
    market: str
    name: str = ""
    price: float | None = None
    chg_pct: float | None = None
    condition_text: str = ""
    status: str = "—无数据"        # ✅触发 / ⏳等待 / ❌无效 / —无数据
    distance: str = ""
    triggered: bool = False
    should_notify: bool = False
    updated_at: str = ""
    source: str = ""


def _should_notify(item: dict) -> bool:
    """距上次触发是否已超过 RETRIGGER_MIN 分钟（True=该弹通知）。"""
    last = item.get("last_trigger_at")
    if not last:
        return True
    try:
        last_dt = datetime.fromisoformat(last)
        now = now_cn()
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=now.tzinfo)
        return (now - last_dt) >= timedelta(minutes=RETRIGGER_MIN)
    except Exception:  # noqa: BLE001
        return True


def scan_all() -> list[ScanRow]:
    """扫描所有启用自选股，返回看板行列表。"""
    out: list[ScanRow] = []
    for item in store.list_enabled():
        ticker = item["ticker"]
        market = item["market"]
        row = ScanRow(ticker=ticker, market=market, condition_text=item["condition"])
        try:
            rt = service.get_realtime(ticker) or {}
            df, src = service.get_daily(ticker)
            snap = latest_snapshot(df) if df is not None and len(df) > 0 else {}
            row.name = rt.get("name", "")
            row.price = rt.get("price")
            row.chg_pct = rt.get("chg_pct")
            row.source = src
            row.updated_at = now_cn().strftime("%H:%M:%S")
            cond = conditions.parse(item["condition"])
            res = conditions.evaluate(cond, snap, rt)
            row.status = res.status
            row.distance = res.distance
            row.triggered = res.triggered
            if res.triggered:
                row.should_notify = _should_notify(item)
                if row.should_notify:
                    store.set_last_trigger(ticker)
        except Exception as e:  # noqa: BLE001
            log.warning("盯盘扫描失败 %s: %s", ticker, e)
            row.status = "—无数据"
        out.append(row)
    return out
