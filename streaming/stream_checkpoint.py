# -*- coding: utf-8 -*-
"""实时管道锚点持久化与断点续传（2026-10 翻新 · 模块三升级版）。

对齐生产级流管道实践（Finnhub Streaming Pipeline / 秒级行情五层架构）：

1. **锚点时间持久化**：每个 topic 的最后处理时间戳（anchor）持久化到 SQLite，
   进程重启/断线重连后可读回，知道「我已经处理到哪一刻」。
2. **断点续传（补数据不重不漏）**：
   - 不漏：恢复时以 anchor 为起点回放补数（backfill），调用方把
     (anchor, now] 区间内的历史消息重新喂入管道；
   - 不重：补数消息先经 SQLite 持久化去重表（processed_ids），
     已处理过的 id 直接跳过，即使消息被重复投递也只生效一次（幂等）。
3. **5 秒滚动窗口（tumbling window）**：与 StreamProcessor 的滑窗互补，
   提供 PyFlink 风格的固定窗口聚合（窗口边界对齐到 epoch 整数倍），
   每个窗口输出 count/mean/sum/min/max/latest。

全部为确定性实现，不依赖 Kafka/Flink，可单测；装了 Kafka 时 anchor 逻辑
同样适用（anchor 即 consumer offset 的时间维抽象）。
"""
from __future__ import annotations

import logging
import os
import sqlite3
import sys
import threading
import time
from contextlib import closing
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.config import DATA_DIR

log = logging.getLogger("stockai.stream.checkpoint")

_CHECKPOINT_DB = DATA_DIR / "stream_checkpoint.db"
_SCHEMA = """
CREATE TABLE IF NOT EXISTS anchors (
    topic TEXT PRIMARY KEY,
    anchor_ts REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS processed_ids (
    id TEXT NOT NULL,
    topic TEXT NOT NULL,
    processed_ts REAL NOT NULL,
    PRIMARY KEY (topic, id)
);
CREATE INDEX IF NOT EXISTS ix_processed_ts ON processed_ids(processed_ts);
"""


class CheckpointStore:
    """锚点 + 幂等去重的 SQLite 持久化层（线程安全）。"""

    def __init__(self, db_path: Optional[Path] = None):
        self._db = Path(db_path) if db_path else _CHECKPOINT_DB
        self._lock = threading.Lock()
        self._db.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as con:
            con.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self._db, timeout=10)
        con.row_factory = sqlite3.Row
        return con

    # ---- 锚点 ----
    def get_anchor(self, topic: str) -> Optional[float]:
        """读回 topic 的锚点时间戳；从未处理过返回 None。"""
        with self._lock, closing(self._connect()) as con:
            row = con.execute("SELECT anchor_ts FROM anchors WHERE topic=?",
                              (topic,)).fetchone()
            return float(row["anchor_ts"]) if row else None

    def set_anchor(self, topic: str, anchor_ts: float) -> None:
        """单调推进锚点（只允许向前，防止乱序消息把锚点回拨）。"""
        with self._lock, closing(self._connect()) as con:
            row = con.execute("SELECT anchor_ts FROM anchors WHERE topic=?",
                              (topic,)).fetchone()
            if row and float(row["anchor_ts"]) >= anchor_ts:
                return
            con.execute(
                "INSERT INTO anchors(topic, anchor_ts, updated_at) VALUES(?,?,?) "
                "ON CONFLICT(topic) DO UPDATE SET anchor_ts=excluded.anchor_ts, "
                "updated_at=excluded.updated_at",
                (topic, float(anchor_ts), time.time()))
            con.commit()

    # ---- 幂等去重 ----
    def mark_processed(self, topic: str, msg_id: str) -> bool:
        """记录消息已处理。返回 True=首次处理；False=重复（应跳过）。"""
        with self._lock, closing(self._connect()) as con:
            try:
                con.execute(
                    "INSERT INTO processed_ids(id, topic, processed_ts) VALUES(?,?,?)",
                    (msg_id, topic, time.time()))
                con.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def is_processed(self, topic: str, msg_id: str) -> bool:
        with self._lock, closing(self._connect()) as con:
            row = con.execute(
                "SELECT 1 FROM processed_ids WHERE topic=? AND id=?",
                (topic, msg_id)).fetchone()
            return row is not None

    def gc(self, older_than_seconds: float = 7 * 86400) -> int:
        """清理过期的幂等记录（默认保留 7 天），返回清理条数。"""
        cutoff = time.time() - older_than_seconds
        with self._lock, closing(self._connect()) as con:
            cur = con.execute("DELETE FROM processed_ids WHERE processed_ts < ?",
                              (cutoff,))
            con.commit()
            return cur.rowcount


class ResumeManager:
    """断点续传管理器：决定重连后从哪个时间点补数，并保证不重不漏。

    用法：
        rm = ResumeManager(store)
        anchor = rm.resume_from("market.tick")        # 补数起点
        for msg in fetch_history(after=anchor):        # 调用方拉取 (anchor, now]
            if rm.should_process("market.tick", msg["id"], msg["ts"]):
                ...正常处理...
    """

    def __init__(self, store: Optional[CheckpointStore] = None,
                 max_backfill_seconds: float = 86400):
        self.store = store or CheckpointStore()
        self.max_backfill = max_backfill_seconds

    def resume_from(self, topic: str, now: Optional[float] = None) -> float:
        """计算补数起点：锚点存在则从锚点续传；否则从 now - max_backfill 开始。

        补数窗口设上限，避免长时间离线后全量回放打爆管道。
        """
        now = now if now is not None else time.time()
        anchor = self.store.get_anchor(topic)
        if anchor is None:
            return now - self.max_backfill
        # 离线过久也只补最近 max_backfill 窗口（更早的走批量历史接口）
        return max(anchor, now - self.max_backfill)

    def should_process(self, topic: str, msg_id: str, msg_ts: float) -> bool:
        """判定消息是否应处理：幂等去重 + 锚点推进（不重不漏的核心）。"""
        first = self.store.mark_processed(topic, msg_id)
        if not first:
            return False          # 重复投递 → 跳过（不重）
        self.store.set_anchor(topic, msg_ts)  # 锚点单调推进
        return True

    def backfill(self, topic: str,
                 messages: Iterable[Dict[str, Any]],
                 handler: Callable[[Dict[str, Any]], Any]) -> Dict[str, int]:
        """对补数消息流执行幂等回放。messages 需含 id/ts 字段。

        返回 {received, processed, skipped_duplicates, skipped_stale}。
        """
        anchor = self.store.get_anchor(topic)
        stats = {"received": 0, "processed": 0,
                 "skipped_duplicates": 0, "skipped_stale": 0}
        for msg in messages:
            stats["received"] += 1
            mid = str(msg.get("id", ""))
            mts = float(msg.get("ts", 0.0))
            if anchor is not None and mts <= anchor and \
                    self.store.is_processed(topic, mid):
                stats["skipped_stale"] += 1
                continue
            if not self.should_process(topic, mid, mts):
                stats["skipped_duplicates"] += 1
                continue
            handler(msg)
            stats["processed"] += 1
        return stats


class TumblingWindow:
    """PyFlink 风格滚动窗口（默认 5 秒），窗口边界对齐 epoch 整数倍。

    每个窗口关闭时（进入下一窗口）通过 on_window_close 回调输出聚合结果：
    {topic, key, window_start, window_end, count, mean, sum, min, max, latest}
    """

    def __init__(self, window_seconds: int = 5,
                 on_window_close: Optional[Callable[[Dict[str, Any]], None]] = None):
        if window_seconds <= 0:
            raise ValueError("window_seconds 必须为正整数")
        self.window_seconds = int(window_seconds)
        self.on_window_close = on_window_close
        self._open: Dict[str, Dict[str, List[tuple]]] = {}  # win_id -> key -> [(ts, value)]
        self._lock = threading.Lock()
        self.closed_windows: List[Dict[str, Any]] = []

    def _window_id(self, ts: float) -> int:
        return int(ts // self.window_seconds)

    def push(self, key: str, value: float, ts: Optional[float] = None,
             topic: str = "market.tick") -> Optional[Dict[str, Any]]:
        """推入数据点；若触发了窗口关闭，返回被关闭窗口的聚合结果（否则 None）。"""
        ts = ts if ts is not None else time.time()
        wid = self._window_id(ts)
        closed: List[Dict[str, Any]] = []
        with self._lock:
            # 关闭所有早于当前窗口的窗口
            for old_wid in sorted(w for w in self._open if w < wid):
                bucket = self._open.pop(old_wid)
                for k, vals in bucket.items():
                    closed.append(self._aggregate(topic, k, old_wid, vals))
            self._open.setdefault(wid, {}).setdefault(key, []).append((ts, float(value)))
        for agg in closed:
            self.closed_windows.append(agg)
            if self.on_window_close:
                try:
                    self.on_window_close(agg)
                except Exception:  # noqa: BLE001
                    pass
        return closed[-1] if closed else None

    def _aggregate(self, topic: str, key: str, wid: int,
                   vals: List[tuple]) -> Dict[str, Any]:
        vs = [v for _, v in vals]
        return {"topic": topic, "key": key,
                "window_start": wid * self.window_seconds,
                "window_end": (wid + 1) * self.window_seconds,
                "count": len(vs), "sum": round(sum(vs), 4),
                "mean": round(sum(vs) / len(vs), 4),
                "min": min(vs), "max": max(vs), "latest": vs[-1]}

    def flush(self, topic: str = "market.tick") -> List[Dict[str, Any]]:
        """强制关闭所有未关闭窗口（进程退出前调用），返回聚合结果列表。"""
        with self._lock:
            out = [self._aggregate(topic, k, wid, vals)
                   for wid, bucket in sorted(self._open.items())
                   for k, vals in bucket.items()]
            self._open.clear()
        for agg in out:
            self.closed_windows.append(agg)
            if self.on_window_close:
                try:
                    self.on_window_close(agg)
                except Exception:  # noqa: BLE001
                    pass
        return out


if __name__ == "__main__":
    import tempfile

    # Windows 下 SQLite 文件句柄释放有延迟，ignore_cleanup_errors 避免清理误报
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        store = CheckpointStore(Path(td) / "cp.db")
        rm = ResumeManager(store, max_backfill_seconds=3600)

        # 首次启动：无锚点 → 从 now-1h 补数
        t0 = time.time()
        assert rm.resume_from("market.tick", now=t0) == t0 - 3600

        # 正常处理 3 条
        for i in range(3):
            assert rm.should_process("market.tick", f"m{i}", t0 - 100 + i)
        # 重复投递 m1 → 跳过（不重）
        assert not rm.should_process("market.tick", "m1", t0 - 99)
        assert store.get_anchor("market.tick") == t0 - 98

        # 模拟断线重连：锚点读回 → 从锚点续传
        rm2 = ResumeManager(store, max_backfill_seconds=3600)
        assert rm2.resume_from("market.tick", now=t0) == t0 - 98

        # 断线期间消息回放（含 1 条已处理的旧消息 + 2 条新消息）
        got = []
        stats = rm2.backfill("market.tick", [
            {"id": "m2", "ts": t0 - 98},   # 已处理 → 跳过
            {"id": "m3", "ts": t0 - 50},   # 新 → 处理
            {"id": "m4", "ts": t0 - 40},   # 新 → 处理
        ], got.append)
        assert stats["processed"] == 2 and stats["received"] == 3, stats
        assert [m["id"] for m in got] == ["m3", "m4"]  # 不重不漏

        # 5 秒滚动窗口：跨窗口触发关闭
        closed = []
        tw = TumblingWindow(5, on_window_close=closed.append)
        base = 1_700_000_000.0
        tw.push("600519", 100.0, ts=base + 0.5)
        tw.push("600519", 102.0, ts=base + 1.0)
        assert closed == []
        tw.push("600519", 105.0, ts=base + 6.0)   # 进入下一窗口 → 关闭上一窗口
        assert len(closed) == 1
        w = closed[0]
        assert w["count"] == 2 and w["mean"] == 101.0 and w["max"] == 102.0
        rest = tw.flush()
        assert len(rest) == 1 and rest[0]["latest"] == 105.0

        print("stream_checkpoint self-check ok "
              f"(backfill={stats}, window_mean={w['mean']})")
