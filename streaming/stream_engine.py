# -*- coding: utf-8 -*-
"""实时流处理管道（模块二）：Kafka 主题总线 + 窗口/去重/情感流式处理。

设计原则（对齐 fin-intelligence-dashboard 的 Kafka ETL 管道，保持零依赖可运行）：
- 后端双模：安装 confluent-kafka 且 broker 可达 → 真实 Kafka；否则自动降级为
  线程安全内存总线（同接口，进程内可用，UI 演示/单机场景零配置）。
- 主题常量：news.raw / news.processed / market.tick / filings.new。
- StreamProcessor 提供：去重（key 布隆式去重）、窗口聚合（5 分钟成交量均值）、
  情感分析（复用 core.data.news_pipeline）、增量 SQLite 缓存写入。
"""
from __future__ import annotations

import hashlib
import json
import logging
import queue
import threading
import time
from collections import deque
from pathlib import Path

from core.config import DATA_DIR

log = logging.getLogger("stockai.stream")

# ---------------- 主题常量 ----------------
TOPIC_NEWS_RAW = "news.raw"
TOPIC_NEWS_PROCESSED = "news.processed"
TOPIC_MARKET_TICK = "market.tick"
TOPIC_FILINGS_NEW = "filings.new"
ALL_TOPICS = [TOPIC_NEWS_RAW, TOPIC_NEWS_PROCESSED, TOPIC_MARKET_TICK, TOPIC_FILINGS_NEW]


def _msg_id(key: str, payload: dict) -> str:
    return hashlib.sha1(f"{key}|{json.dumps(payload, sort_keys=True, ensure_ascii=False)}"
                        .encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# 内存总线后端（零依赖；线程安全）
# ---------------------------------------------------------------------------

class _MemoryBackend:
    def __init__(self, max_queue: int = 1000):
        self._queues: dict[str, queue.Queue] = {t: queue.Queue(maxsize=max_queue)
                                                 for t in ALL_TOPICS}
        self._lock = threading.Lock()
        self._published: dict[str, int] = {t: 0 for t in ALL_TOPICS}
        self._dropped: dict[str, int] = {t: 0 for t in ALL_TOPICS}
        self._last_ts: dict[str, float] = {}
        self._rate: dict[str, deque] = {t: deque(maxlen=120) for t in ALL_TOPICS}

    def publish(self, topic: str, key: str, payload: dict) -> dict:
        msg = {"id": _msg_id(key, payload), "topic": topic, "key": key,
               "payload": payload, "ts": time.time()}
        with self._lock:
            try:
                self._queues[topic].put_nowait(msg)
            except queue.Full:
                self._dropped[topic] += 1
            self._published[topic] += 1
            self._last_ts[topic] = time.time()
            self._rate[topic].append(time.time())
        return msg

    def poll(self, topic: str, timeout: float = 0.1):
        try:
            return self._queues[topic].get(timeout=timeout)
        except queue.Empty:
            return None

    def pending(self, topic: str) -> int:
        return self._queues[topic].qsize()

    def stats(self) -> dict:
        out = {}
        now = time.time()
        with self._lock:
            for t in ALL_TOPICS:
                rate = 0.0
                if self._rate[t]:
                    win = max(1.0, now - self._rate[t][0])
                    rate = round(len(self._rate[t]) * 60.0 / win, 1)
                out[t] = {
                    "published": self._published[t],
                    "dropped": self._dropped[t],
                    "pending": self._queues[t].qsize(),
                    "rate_per_min": rate,
                    "last_ts": self._last_ts.get(t),
                    "backend": "memory",
                }
        return out


# ---------------------------------------------------------------------------
# Kafka 后端（confluent-kafka 可选）
# ---------------------------------------------------------------------------

class _KafkaBackend:
    def __init__(self, bootstrap: str = "localhost:9092"):
        from confluent_kafka import Producer
        self._bootstrap = bootstrap
        self._producer = Producer({"bootstrap.servers": bootstrap})
        self._published: dict[str, int] = {t: 0 for t in ALL_TOPICS}
        self._lock = threading.Lock()
        self._last_ts: dict[str, float] = {}

    def publish(self, topic: str, key: str, payload: dict) -> dict:
        msg = {"id": _msg_id(key, payload), "topic": topic, "key": key,
               "payload": payload, "ts": time.time()}
        try:
            self._producer.produce(topic, key=key.encode("utf-8"),
                                   value=json.dumps(payload, ensure_ascii=False).encode("utf-8"))
            self._producer.poll(0)
            with self._lock:
                self._published[topic] += 1
                self._last_ts[topic] = time.time()
        except Exception as e:  # noqa: BLE001
            log.warning("stream: kafka publish 失败 %s", str(e)[:80])
        return msg

    def pending(self, topic: str) -> int:
        return 0  # broker 侧积压不在本地可见；由 UI 标注

    def stats(self) -> dict:
        return {t: {"published": n, "dropped": 0, "pending": 0,
                    "rate_per_min": 0.0, "last_ts": self._last_ts.get(t),
                    "backend": "kafka"} for t, n in self._published.items()}


# ---------------------------------------------------------------------------
# 流引擎：统一入口（auto：Kafka 可用即用，否则内存）
# ---------------------------------------------------------------------------

class StreamEngine:
    def __init__(self, mode: str = "auto", bootstrap: str = "localhost:9092"):
        self.mode = mode
        self.bootstrap = bootstrap
        self._backend = None
        if mode in ("auto", "kafka"):
            try:
                self._backend = _KafkaBackend(bootstrap)
                self.mode = "kafka"
                log.info("stream: 使用 Kafka 后端 (%s)", bootstrap)
            except Exception as e:  # noqa: BLE001
                log.warning("stream: Kafka 不可用(%s)，降级内存总线", str(e)[:80])
                if mode == "kafka":
                    raise
        if self._backend is None:
            self._backend = _MemoryBackend()
            self.mode = "memory"

    def publish(self, topic: str, key: str, payload: dict) -> dict:
        if topic not in ALL_TOPICS:
            raise ValueError(f"未知 topic：{topic}")
        return self._backend.publish(topic, key, payload)

    def pending(self, topic: str) -> int:
        return self._backend.pending(topic)

    def stats(self) -> dict:
        return self._backend.stats()

    def backend_name(self) -> str:
        return self.mode


# ---------------------------------------------------------------------------
# 流处理器：去重 / 窗口聚合 / 情感分析 / SQLite 增量缓存
# ---------------------------------------------------------------------------

_STREAM_DB = DATA_DIR / "stream_cache.db"
_SCHEMA = """
CREATE TABLE IF NOT EXISTS tick_cache (
    id TEXT PRIMARY KEY,
    code TEXT NOT NULL,
    price REAL,
    volume REAL,
    ts REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_tick_code ON tick_cache(code, ts);
CREATE TABLE IF NOT EXISTS news_cache (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    sentiment TEXT,
    ts REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS stream_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    topic TEXT NOT NULL,
    detail TEXT NOT NULL
);
"""


def _db_conn():
    import sqlite3
    from contextlib import closing, contextmanager

    @contextmanager
    def _open():
        con = sqlite3.connect(_STREAM_DB)
        con.row_factory = sqlite3.Row
        con.executescript(_SCHEMA)
        with closing(con):
            yield con
            con.commit()

    return _open()


class StreamProcessor:
    """流式处理管线：摄取 → 清洗(去重/校验) → 分析(情感/聚合) → 输出。"""

    def __init__(self, engine: StreamEngine, window_seconds: int = 300):
        self.engine = engine
        self.window_seconds = window_seconds
        self._seen: set[str] = set()
        self._seen_lock = threading.Lock()
        # 窗口聚合：topic -> key -> deque[(ts, value)]
        self._windows: dict[str, dict[str, deque]] = {}
        self._windows_lock = threading.Lock()
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self.duplicates_skipped = 0
        self.processed = 0
        # 对外回调（UI 集成）
        self.on_event = None  # callable(topic, msg, agg)  工作线程回调
        self.filing_ai_parser = None  # callable(filing_dict) -> summary；公告 AI 解析钩子

    # ---- 工具 ----
    def _dedup(self, msg_id: str) -> bool:
        with self._seen_lock:
            if msg_id in self._seen:
                self.duplicates_skipped += 1
                return True
            self._seen.add(msg_id)
            return False

    def _window_push(self, topic: str, key: str, value: float):
        with self._windows_lock:
            w = self._windows.setdefault(topic, {}).setdefault(key, deque())
            w.append((time.time(), value))

    def _window_agg(self, topic: str, key: str) -> dict | None:
        """滑窗聚合：窗口内 count / mean / latest / sum。过期条目剔除。"""
        now = time.time()
        with self._windows_lock:
            w = self._windows.get(topic, {}).get(key)
            if not w:
                return None
            while w and now - w[0][0] > self.window_seconds:
                w.popleft()
            if not w:
                return None
            vals = [v for _, v in w]
            return {"window_s": self.window_seconds, "count": len(vals),
                    "mean": round(sum(vals) / len(vals), 4),
                    "latest": vals[-1], "sum": round(sum(vals), 4)}

    # ---- 处理函数 ----
    def process_news(self, raw: dict) -> dict:
        """news.raw → 去重 → 情感分析 → news.processed + SQLite。"""
        title = raw.get("title") or raw.get("text") or ""
        msg_id = raw.get("id") or _msg_id(raw.get("key", ""), {"title": title})
        if self._dedup(msg_id):
            return {"skipped": True, "id": msg_id}
        from core.sentiment import analyze_sentiment
        sentiment = analyze_sentiment(title[:300])
        out = {"id": msg_id, "title": title[:200], "source": raw.get("source", ""),
               "sentiment": sentiment, "ts": raw.get("ts", time.time())}
        self.engine.publish(TOPIC_NEWS_PROCESSED, out["id"], out)
        with _db_conn() as c:
            c.execute("INSERT OR IGNORE INTO news_cache(id,title,sentiment,ts) VALUES(?,?,?,?)",
                      (out["id"], out["title"], sentiment, out["ts"]))
        self.processed += 1
        return out

    def process_tick(self, raw: dict) -> dict:
        """market.tick → 去重 → 窗口聚合（默认5分钟均值） → SQLite 增量缓存。"""
        code = raw.get("code") or raw.get("key", "")  # key 兜底（发布方可能省略 code）
        price = float(raw.get("price", 0.0))
        volume = float(raw.get("volume", 0.0))
        msg_id = raw.get("id") or _msg_id(code, {"price": price, "ts": raw.get("ts", 0)})
        if self._dedup(msg_id):
            return {"skipped": True, "id": msg_id}
        self._window_push(TOPIC_MARKET_TICK, code, volume)
        agg = self._window_agg(TOPIC_MARKET_TICK, code)
        with _db_conn() as c:
            c.execute("INSERT OR REPLACE INTO tick_cache(id,code,price,volume,ts) VALUES(?,?,?,?,?)",
                      (msg_id, code, price, volume, raw.get("ts", time.time())))
        self.processed += 1
        return {"id": msg_id, "code": code, "price": price, "volume": volume,
                "agg": agg, "ts": raw.get("ts", time.time())}

    def process_filing(self, raw: dict, ai_parser=None) -> dict:
        """filings.new → 去重 → （可选）AI 解析回调生成摘要卡片。"""
        title = raw.get("title", "")
        msg_id = raw.get("id") or _msg_id(raw.get("key", ""), {"title": title})
        if self._dedup(msg_id):
            return {"skipped": True, "id": msg_id}
        out = {"id": msg_id, "title": title[:200], "code": raw.get("code", ""),
               "ts": raw.get("ts", time.time())}
        if ai_parser is not None:
            try:
                out["summary"] = ai_parser(out)
            except Exception as e:  # noqa: BLE001
                out["summary"] = f"AI 解析失败：{str(e)[:80]}"
        with _db_conn() as c:
            c.execute("INSERT INTO stream_log(ts,topic,detail) VALUES(?,?,?)",
                      (out["ts"], TOPIC_FILINGS_NEW,
                       json.dumps(out, ensure_ascii=False)[:300]))
        self.processed += 1
        return out

    # ---- 消费循环 ----
    def start(self):
        """为每个 topic 启动消费线程（内存后端）。Kafka 后端需外部配置消费者。"""
        if self.engine.backend_name() != "memory":
            log.info("stream: Kafka 后端由外部消费者消费（本进程只负责生产与处理钩子）")
            return
        self._stop.clear()
        for topic in ALL_TOPICS:
            t = threading.Thread(target=self._consume_loop, args=(topic,), daemon=True)
            t.start()
            self._threads.append(t)

    def _consume_loop(self, topic: str):
        while not self._stop.is_set():
            try:
                msg = self.engine._backend.poll(topic, timeout=0.3)
            except AttributeError:
                return
            if msg is None:
                continue
            try:
                # 注入发布时生成的 id/key，保证去重口径与 publish 一致
                payload = dict(msg.get("payload") or {})
                payload.setdefault("id", msg.get("id"))
                payload.setdefault("key", msg.get("key"))
                result = None
                if topic == TOPIC_NEWS_RAW:
                    result = self.process_news(payload)
                elif topic == TOPIC_MARKET_TICK:
                    result = self.process_tick(payload)
                elif topic == TOPIC_FILINGS_NEW:
                    result = self.process_filing(payload, self.filing_ai_parser)
                elif topic == TOPIC_NEWS_PROCESSED:
                    result = {"id": msg["id"], "forwarded": True}
                if self.on_event:
                    self.on_event(topic, msg, result)
            except Exception as e:  # noqa: BLE001
                log.warning("stream: 处理 %s 失败 %s", topic, str(e)[:100])

    def stop(self):
        self._stop.set()
        for t in self._threads:
            t.join(timeout=2)
        self._threads.clear()

    def stats(self) -> dict:
        base = self.engine.stats()
        base["_processor"] = {"processed": self.processed,
                              "duplicates_skipped": self.duplicates_skipped}
        return base


if __name__ == "__main__":
    eng = StreamEngine(mode="auto")
    proc = StreamProcessor(eng, window_seconds=60)
    proc.start()
    eng.publish(TOPIC_NEWS_RAW, "n1", {"title": "某公司净利润增长超预期，股价大涨"})
    eng.publish(TOPIC_NEWS_RAW, "n1", {"title": "某公司净利润增长超预期，股价大涨"})  # 重复 → 去重
    eng.publish(TOPIC_MARKET_TICK, "600519", {"price": 1700.0, "volume": 1000})
    eng.publish(TOPIC_MARKET_TICK, "600519", {"price": 1702.0, "volume": 1500})
    eng.publish(TOPIC_FILINGS_NEW, "f1", {"title": "关于重大合同签订的公告", "code": "600519"})
    time.sleep(1.5)
    proc.stop()
    import pprint
    pprint.pprint(proc.stats())
