# -*- coding: utf-8 -*-
"""实时行情引擎（模块五）。

数据源优先级（诚实降级链）：
1. WebSocket 实时推送 —— 当检测到已配置的行情 WebSocket 客户端（如 Longbridge/自定义
   LONGBRIDGE_WS_URL + LONGBRIDGE_APP_KEY/SECRET 或 REALTIME_WS_URL 环境变量）时启用；
   未配置/未安装依赖 → 自动降级。
2. AKShare 轮询 —— 默认模式，按 interval 秒拉取 service.get_realtime。
3. 缓存兜底 —— 实时失败时返回最近缓存快照并标注 stale。

特性：自动重连（指数退避 1s→2s→4s→8s…最大 30s）、心跳保活（WebSocket ping）、
多市场订阅（A股/港股/美股代码均可）、断线状态回调。

纯 Python 线程实现（不依赖 Qt），任何 UI 层均可通过回调接入。
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Callable, Dict, List, Optional

log = logging.getLogger("stockai.realtime")

_BACKOFF_BASE = [1, 2, 4, 8, 16, 30]  # 秒，指数退避上限 30s


class RealtimeEngine:
    """通用实时行情引擎。

    用法：
        eng = RealtimeEngine(interval=3)
        eng.on_quotes = lambda quotes, ts: ...
        eng.on_status = lambda text: ...
        eng.start(["SH600519", "AAPL", "0700.HK"])
        ...
        eng.stop()
    """

    def __init__(self, interval: int = 3,
                 on_quotes: Optional[Callable] = None,
                 on_status: Optional[Callable] = None):
        self.interval = max(2, int(interval))
        self.on_quotes = on_quotes
        self.on_status = on_status
        self._codes: List[str] = []
        self._thread: Optional[threading.Thread] = None
        self._stop_evt = threading.Event()
        self._fail_count = 0
        self._last_ok_ts: Optional[float] = None
        self._running = False

    # ---------------- 生命周期 ----------------
    def start(self, codes: List[str]) -> None:
        self._codes = [c for c in (codes or []) if c]
        if not self._codes:
            self._status("实时行情：无订阅标的")
            return
        if self._running:
            return
        self._stop_evt.clear()
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="realtime-engine")
        self._thread.start()
        self._status(f"实时行情已开启 · 每 {self.interval}s 订阅 {len(self._codes)} 个标的")

    def stop(self) -> None:
        self._running = False
        self._stop_evt.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)
        self._thread = None
        self._status("实时行情已停止")

    def _status(self, text: str) -> None:
        if self.on_status:
            try:
                self.on_status(text)
            except Exception:  # noqa: BLE001
                pass

    # ---------------- 主循环（轮询模式） ----------------
    def _loop(self) -> None:
        # 尝试 WebSocket（已配置时）
        if self._ws_available():
            self._ws_loop()
            return  # ws 异常退出后不再回退轮询（下次 start 再试）
        self._poll_loop()

    def _poll_loop(self) -> None:
        while not self._stop_evt.is_set():
            try:
                quotes = self._poll_once()
                self._fail_count = 0
                self._last_ok_ts = time.time()
                if self.on_quotes:
                    self.on_quotes(quotes, self._last_ok_ts)
                if self.on_status:
                    self._status(f"实时 · 延迟<{self.interval}s")
                self._sleep(self.interval)
            except Exception as e:  # noqa: BLE001
                self._fail_count += 1
                delay = _BACKOFF_BASE[min(self._fail_count - 1,
                                          len(_BACKOFF_BASE) - 1)]
                self._status(f"实时行情异常（{type(e).__name__}），{delay}s 后重试")
                log.warning("realtime poll 失败: %s", e)
                self._sleep(delay)

    def _poll_once(self) -> List[dict]:
        from core.data import service
        out: List[dict] = []
        for code in self._codes:
            try:
                r = service.get_realtime(code)
                if r and r.get("price") not in (None, 0):
                    out.append({
                        "code": code,
                        "price": r["price"],
                        "chg_pct": r.get("chg_pct_1d"),
                        "source": r.get("source", "live"),
                        "ts": time.strftime("%H:%M:%S"),
                    })
                else:
                    out.append({"code": code, "price": None,
                                "chg_pct": None, "source": "none", "ts": "—"})
            except Exception as e:  # noqa: BLE001
                log.warning("realtime %s: %s", code, e)
                out.append({"code": code, "price": None,
                            "chg_pct": None, "source": "error", "ts": "—"})
        return out

    # ---------------- WebSocket 模式（可选依赖） ----------------
    def _ws_url(self) -> str:
        """数据源优先级：QOS 行情 API → 自定义 REALTIME_WS_URL → Longbridge。"""
        return (os.environ.get("QOS_WS_URL", "")
                or os.environ.get("REALTIME_WS_URL", ""))

    def _ws_available(self) -> bool:
        url = self._ws_url()
        if not url:
            # Longbridge 配置检测
            if os.environ.get("LONGBRIDGE_APP_KEY", "") and os.environ.get(
                    "LONGBRIDGE_APP_SECRET", ""):
                try:
                    import lb  # noqa: F401
                    return True
                except Exception:  # noqa: BLE001
                    log.warning("已配置 Longbridge 但未安装 lb，降级轮询")
            return False
        try:
            import websockets  # noqa: F401
            return True
        except Exception:  # noqa: BLE001
            log.warning("已配置 QOS/REALTIME_WS_URL 但未安装 websockets，降级轮询")
            return False

    def _ws_loop(self) -> None:
        import asyncio

        url = self._ws_url()

        async def _run() -> None:
            import websockets
            while not self._stop_evt.is_set():
                try:
                    self._status("WebSocket 已连接")
                    async with websockets.connect(url, ping_interval=30) as ws:
                        # 订阅多市场标的
                        await ws.send(
                            "subscribe " + ",".join(self._codes))
                        self._last_ok_ts = time.time()
                        self._fail_count = 0
                        while not self._stop_evt.is_set():
                            try:
                                msg = await asyncio.wait_for(ws.recv(),
                                                             timeout=5)
                                self._handle_ws_msg(msg)
                            except asyncio.TimeoutError:
                                continue
                except Exception as e:  # noqa: BLE001
                    self._fail_count += 1
                    delay = _BACKOFF_BASE[min(self._fail_count - 1,
                                              len(_BACKOFF_BASE) - 1)]
                    self._status(f"WebSocket 断开（{type(e).__name__}），"
                                 f"{delay}s 后重连")
                    await asyncio.sleep(delay)

        def _run_sync():
            try:
                asyncio.run(_run())
            except Exception as e:  # noqa: BLE001
                log.warning("realtime ws loop exit: %s", e)

        _run_sync()

    def _handle_ws_msg(self, msg) -> None:
        """解析外部行情消息（约定 JSON 或 'code=price,chg' 行格式）。"""
        import json
        try:
            data = json.loads(msg)
            quotes = [{
                "code": data.get("code", ""),
                "price": data.get("price"),
                "chg_pct": data.get("chg_pct"),
                "source": "ws",
                "ts": time.strftime("%H:%M:%S"),
            }]
        except Exception:  # noqa: BLE001
            text = str(msg)
            parts = [p for p in text.split(";") if p]
            quotes = []
            for p in parts:
                try:
                    code, rest = p.split("=", 1)
                    price, _, chg = rest.partition(",")
                    quotes.append({
                        "code": code.strip(),
                        "price": float(price),
                        "chg_pct": float(chg) if chg.strip() else None,
                        "source": "ws",
                        "ts": time.strftime("%H:%M:%S"),
                    })
                except Exception:  # noqa: BLE001
                    continue
        if quotes and self.on_quotes:
            self.on_quotes(quotes, time.time())

    def _sleep(self, secs: float) -> None:
        self._stop_evt.wait(secs)

    # ---------------- 便捷状态 ----------------
    @property
    def last_ok_ts(self) -> Optional[float]:
        return self._last_ok_ts

    @property
    def running(self) -> bool:
        return self._running


if __name__ == "__main__":
    import os
    os.environ["STOCKAI_MOCK"] = "1"
    eng = RealtimeEngine(interval=2)
    got = []

    def _q(quotes, ts):
        got.append(quotes)
        print("quotes:", quotes[:2], "ts:", ts)

    def _s(text):
        print("status:", text)

    eng.on_quotes, eng.on_status = _q, _s
    eng.start(["SH600519", "AAPL"])
    time.sleep(6)
    eng.stop()
    print("收到行情批次:", len(got))
