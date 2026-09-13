# -*- coding: utf-8 -*-
"""Kronos 金融K线基础模型短期预测（本地，CPU）。

模型：NeoQuasar/Kronos-small（AAAI2026，~25M 参数，max_context=512）。
设计：
- 懒加载单例：sys.path 指向 external/kronos，from_pretrained 走 hf-mirror；
- 取最近 ~400 根日 OHLC，预测未来 5 个工作日收盘方向与幅度；
- 输出 {up_pct, direction, note} 作为程序短期K线观点，喂情绪/风控；
- 任何失败（模型/权重/推理）优雅降级 None，绝不拖垮主流程；
- 仅在用户显式开启或调用时加载（首次需下载权重，慢）。
"""
from __future__ import annotations

import logging
import os

import pandas as pd

log = logging.getLogger("stockai.ml.kronos")

_PRED = None
_READY: bool | None = None


def _load() -> bool:
    global _PRED, _READY
    if _READY is not None:
        return _READY
    try:
        os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
        import sys
        root = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))))  # D:\StockAIPredictor
        kpath = os.path.join(root, "external", "kronos")
        if kpath not in sys.path:
            sys.path.insert(0, kpath)
        from model import Kronos, KronosPredictor, KronosTokenizer
        tok = KronosTokenizer.from_pretrained("NeoQuasar/Kronos-Tokenizer-base")
        mdl = Kronos.from_pretrained("NeoQuasar/Kronos-small")
        _PRED = KronosPredictor(mdl, tok, max_context=512)
        _READY = True
        log.info("Kronos-small 加载完成")
    except Exception as e:  # noqa: BLE001
        log.warning("Kronos 加载失败（降级）：%s", str(e)[:160])
        _READY = False
    return _READY


def forecast(bars: pd.DataFrame, pred_len: int = 5) -> dict:
    """预测未来 pred_len 个工作日收盘方向。返回 {up_pct, direction, note}。"""
    if bars is None or len(bars) < 60:
        return {"up_pct": None, "direction": "数据不足", "note": ""}
    if not _load():
        return {"up_pct": None, "direction": "不可用", "note": "Kronos未加载"}
    try:
        df = bars.sort_index().tail(400).copy()
        df["timestamps"] = df.index
        x_df = df[["open", "high", "low", "close"]]
        x_ts = df["timestamps"]
        last_day = df.index[-1]
        y_ts = pd.Series(pd.bdate_range(last_day, periods=pred_len + 1)[1:])
        out = _PRED.predict(df=x_df, x_timestamp=x_ts, y_timestamp=y_ts,
                            pred_len=pred_len, T=1.0, top_p=0.9, sample_count=1)
        future_close = float(out["close"].iloc[-1])
        now_close = float(df["close"].iloc[-1])
        up_pct = (future_close / now_close - 1.0) * 100.0
        if up_pct > 1.0:
            direction = "Kronos看涨"
        elif up_pct < -1.0:
            direction = "Kronos看跌"
        else:
            direction = "Kronos震荡"
        return {"up_pct": round(up_pct, 2), "direction": direction,
                "note": f"未来{pred_len}日预测收盘{future_close:.2f}（较今{up_pct:+.1f}%）"}
    except Exception as e:  # noqa: BLE001
        log.warning("Kronos 预测失败：%s", str(e)[:160])
        return {"up_pct": None, "direction": "预测失败", "note": str(e)[:100]}
