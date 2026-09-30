# -*- coding: utf-8 -*-
"""tick 级回放引擎（模块六 · 参考 CandleKit 确定性回放）。

把日线/K线 bars 合成为确定性 tick 序列（按成交量权重插值），支持
播放/暂停、步进 ±1、速度控制（1x/2x/4x/8x）、跳转，回调通知当前索引。

纯数据层（无 GUI 依赖）：UI 层可把 on_step 接到图表高亮/十字光标。
tick 为合成序列，用于策略演示与教学，非交易所原始逐笔。
"""
from __future__ import annotations

import logging
from typing import Callable, List, Optional

import pandas as pd

log = logging.getLogger("stockai.core.quant.playback")


def synthesize_ticks(bars: pd.DataFrame, ticks_per_bar: int = 8) -> List[dict]:
    """把 OHLCV bars 合成为确定性 tick 序列。

    每根 bar 生成 ticks_per_bar 个 tick：开盘→收盘线性推进（含高/低毛刺），
    volume 均摊。返回 [{i: 全局K线索引, price, volume, ts}]。
    """
    if bars is None or len(bars) == 0:
        return []
    out: List[dict] = []
    for pos, (idx, row) in enumerate(bars.iterrows()):
        o, c = float(row.get("open", 0)), float(row.get("close", 0))
        hi, lo = float(row.get("high", max(o, c))), float(row.get("low", min(o, c)))
        v = float(row.get("volume", 0)) / max(1, ticks_per_bar)
        for k in range(ticks_per_bar):
            frac = k / max(1, ticks_per_bar - 1)
            price = o + (c - o) * frac
            # 高/低毛刺：在 1/4 与 3/4 处触及
            if k == ticks_per_bar // 4:
                price = hi
            elif k == ticks_per_bar * 3 // 4:
                price = lo
            out.append({"i": pos, "price": round(price, 4),
                        "volume": round(v, 2),
                        "ts": pos + frac})
    return out


class PlaybackEngine:
    """可播放的 tick 序列引擎（同步回调式）。"""

    def __init__(self, bars: Optional[pd.DataFrame] = None,
                 ticks_per_bar: int = 8):
        self.ticks: List[dict] = synthesize_ticks(bars, ticks_per_bar)
        self._pos = 0
        self._playing = False
        self._speed = 1.0
        self._callbacks: List[Callable[[dict], None]] = []

    # ---- 控制 ----
    def play(self) -> None:
        self._playing = True

    def pause(self) -> None:
        self._playing = False

    def toggle(self) -> bool:
        self._playing = not self._playing
        return self._playing

    def step(self, delta: int = 1) -> Optional[dict]:
        """步进 ±1（暂停态）。返回当前 tick 或 None（越界）。"""
        if not self.ticks:
            return None
        self._pos = max(0, min(len(self.ticks) - 1, self._pos + delta))
        cur = self.ticks[self._pos]
        self._emit(cur)
        return cur

    def jump(self, pos: int) -> Optional[dict]:
        if not self.ticks:
            return None
        self._pos = max(0, min(len(self.ticks) - 1, pos))
        cur = self.ticks[self._pos]
        self._emit(cur)
        return cur

    def set_speed(self, mult: float) -> None:
        self._speed = max(0.25, min(8.0, mult))

    # ---- 播放循环（UI 定时器每秒调用 advance 一次） ----
    def advance(self, dt: float = 1.0) -> Optional[dict]:
        """按速度推进（每秒调用；speed=2 → 每调用前进 2 tick）。"""
        if not self._playing or not self.ticks:
            return None
        n = max(1, int(round(self._speed * dt)))
        self._pos = min(len(self.ticks) - 1, self._pos + n)
        if self._pos >= len(self.ticks) - 1:
            self._playing = False
        cur = self.ticks[self._pos]
        self._emit(cur)
        return cur

    # ---- 状态 ----
    @property
    def position(self) -> int:
        return self._pos

    @property
    def playing(self) -> bool:
        return self._playing

    @property
    def speed(self) -> float:
        return self._speed

    @property
    def total(self) -> int:
        return len(self.ticks)

    @property
    def progress(self) -> float:
        return self._pos / max(1, len(self.ticks) - 1)

    # ---- 观察者 ----
    def on_step(self, cb: Callable[[dict], None]) -> None:
        self._callbacks.append(cb)

    def _emit(self, tick: dict) -> None:
        for cb in self._callbacks:
            try:
                cb(tick)
            except Exception as e:  # noqa: BLE001
                log.debug("回放回调失败：%s", e)


if __name__ == "__main__":
    rng = __import__("numpy").random.default_rng(3)
    close = pd.Series(100 * __import__("numpy").cumprod(
        1 + rng.normal(0.001, 0.01, 40)))
    bars = pd.DataFrame({"open": close, "high": close * 1.005,
                         "low": close * 0.995, "close": close,
                         "volume": rng.integers(1e5, 3e5, 40)},
                        index=pd.RangeIndex(40))
    tks = synthesize_ticks(bars, ticks_per_bar=8)
    assert len(tks) == 40 * 8
    assert tks[0]["i"] == 0 and tks[-1]["i"] == 39
    assert tks[0]["price"] > 0
    eng = PlaybackEngine(bars, ticks_per_bar=8)
    seen: list = []
    eng.on_step(lambda t: seen.append(t["price"]))
    eng.step(1)
    assert seen and eng.position == 1
    eng.jump(100)
    assert eng.position == 100
    eng.play()
    eng.advance(dt=1.0)
    assert eng.playing or eng.position >= eng.total - 1
    eng.set_speed(4.0)
    assert eng.speed == 4.0
    empty = PlaybackEngine(None)
    assert empty.total == 0 and empty.step(1) is None
    print(f"playback self-check ok (ticks={len(tks)}, "
          f"pos={eng.position}/{eng.total}, progress={eng.progress:.2f})")
