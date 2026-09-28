# -*- coding: utf-8 -*-
"""Sidecar 行情网关（统一行情接入层）。

参考架构复盘案例：Go/Rust Sidecar 负责 WebSocket 建连、异构数据清洗、OrderBook 维护；
Python 策略层通过 ZeroMQ / 共享内存 / stdio 读取清洗后的标准 JSON 行情。

本模块提供：
- 统一 TickMessage 协议（JSON，字段规范）；
- SidecarGateway：外部进程协议（stdio JSON Lines）+ 进程管理（可选启动）；
- 内置模拟 sidecar（无外部进程时演示标准数据流）。

依赖说明：zmq 可选；未安装时使用内置队列通道，协议不变。
"""
from __future__ import annotations

import json
import logging
import queue
import subprocess
import threading
import time
from dataclasses import dataclass, field

log = logging.getLogger("stockai.pipeline.sidecar")

# 统一行情协议字段（清洗后标准 JSON）
_TICK_FIELDS = ("ticker", "ts", "px", "bid", "ask", "bidsize", "asksize", "vol", "src")


@dataclass
class TickMessage:
    ticker: str
    px: float
    ts: float
    bid: float | None = None
    ask: float | None = None
    bidsize: int = 0
    asksize: int = 0
    vol: int = 0
    src: str = "sidecar"

    def to_json(self) -> str:
        return json.dumps({k: getattr(self, k) for k in _TICK_FIELDS}, ensure_ascii=False)

    @classmethod
    def from_json(cls, line: str) -> "TickMessage":
        d = json.loads(line)
        return cls(**{k: d.get(k) for k in _TICK_FIELDS})


class SidecarGateway:
    """Sidecar 行情网关。

    - 通道优先级：zmq(可选) > 内置队列；
    - 外部进程：`spawn(cmd)` 启动 sidecar 可执行文件（stdio JSON Lines）；
      无外部进程时 `pump_simulated()` 产生模拟 tick 演示协议。
    """

    def __init__(self, use_zmq: bool = False):
        self.use_zmq = use_zmq
        self._queue: queue.Queue = queue.Queue(maxsize=2000)
        self._dropped = 0
        self._proc: subprocess.Popen | None = None
        self._reader: threading.Thread | None = None
        self._zmq = None
        if use_zmq:
            try:
                import zmq  # noqa: F401
                self._zmq = "zmq"  # 真实连接需 address 配置
            except ImportError:
                log.warning("zmq 未安装，Sidecar 降级为内置队列通道（协议不变）")
                self.use_zmq = False

    # ---------- 消费 ----------
    def push(self, tick: TickMessage) -> bool:
        """向 Python 策略层推送 tick（带背压）。"""
        try:
            self._queue.put_nowait(tick)
            return True
        except queue.Full:
            self._dropped += 1
            return False

    def poll(self, timeout: float = 0.1) -> TickMessage | None:
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def drain(self, limit: int = 100) -> list[TickMessage]:
        out = []
        for _ in range(limit):
            t = self.poll(0)
            if t is None:
                break
            out.append(t)
        return out

    # ---------- 外部进程 ----------
    def spawn(self, cmd: list[str]) -> bool:
        """启动真实 sidecar 进程（stdio JSON Lines 协议）。"""
        try:
            self._proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, bufsize=1)
            self._reader = threading.Thread(target=self._read_loop, daemon=True)
            self._reader.start()
            return True
        except Exception as e:  # noqa: BLE001
            log.warning("Sidecar 进程启动失败: %s", e)
            return False

    def _read_loop(self) -> None:
        while self._proc and self._proc.poll() is None:
            line = self._proc.stdout.readline()  # type: ignore[union-attr]
            if not line:
                break
            try:
                self.push(TickMessage.from_json(line.strip()))
            except Exception:  # noqa: BLE001
                continue

    # ---------- 模拟 ----------
    def pump_simulated(self, ticker: str, n: int = 10, step: float = 0.1,
                       base: float = 100.0) -> int:
        """无外部进程时的演示通道：产生 n 条标准 tick。"""
        px = base
        pushed = 0
        for i in range(n):
            px = px + step * (0.5 if i % 2 == 0 else -0.3)
            t = TickMessage(ticker=ticker, px=round(px, 2), ts=time.time(),
                            bid=round(px - 0.01, 2), ask=round(px + 0.01, 2),
                            vol=i * 100, src="simulated")
            if self.push(t):
                pushed += 1
        return pushed

    def stats(self) -> dict:
        return {"queued": self._queue.qsize(), "dropped": self._dropped,
                "channel": "zmq" if self._zmq else "builtin-queue",
                "proc_alive": bool(self._proc and self._proc.poll() is None)}


if __name__ == "__main__":
    gw = SidecarGateway()
    n = gw.pump_simulated("SH600519", n=8)
    assert n == 8
    ticks = gw.drain(100)
    assert len(ticks) == 8
    assert isinstance(ticks[0], TickMessage) and ticks[0].px > 0
    # JSON 协议往返
    assert TickMessage.from_json(ticks[0].to_json()).px == ticks[0].px
    # 背压
    gw2 = SidecarGateway()
    for i in range(3000):
        gw2.push(TickMessage(ticker="X", px=float(i), ts=time.time()))
    assert gw2.stats()["dropped"] > 0
    print(f"PASS sidecar_gateway 自测 {gw.stats()}")
