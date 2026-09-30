# -*- coding: utf-8 -*-
"""模块二 · 实时流处理管道：unit tests。

覆盖：内存总线发布/统计、去重、情感分析、窗口聚合、SQLite 增量缓存、
Kafka 不可用时自动降级。
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("STOCKAI_MOCK", "1")

import time

from streaming.stream_engine import (ALL_TOPICS, StreamEngine, StreamProcessor,
                                     TOPIC_FILINGS_NEW, TOPIC_MARKET_TICK,
                                     TOPIC_NEWS_PROCESSED, TOPIC_NEWS_RAW,
                                     _MemoryBackend, _db_conn, _msg_id)


def test_engine_auto_fallback_memory():
    eng = StreamEngine(mode="auto", bootstrap="127.0.0.1:1")  # 不可达 → 内存
    assert eng.backend_name() == "memory"
    s = eng.stats()
    assert set(s.keys()) == set(ALL_TOPICS)
    assert s[TOPIC_NEWS_RAW]["backend"] == "memory"


def test_publish_and_stats():
    eng = StreamEngine(mode="memory")
    eng.publish(TOPIC_NEWS_RAW, "k1", {"title": "增长超预期"})
    eng.publish(TOPIC_NEWS_RAW, "k2", {"title": "下滑风险"})
    s = eng.stats()
    assert s[TOPIC_NEWS_RAW]["published"] == 2


def test_unknown_topic_rejected():
    eng = StreamEngine(mode="memory")
    try:
        eng.publish("bad.topic", "k", {})
        assert False, "应拒绝未知 topic"
    except ValueError:
        pass


def test_processor_news_dedup_sentiment():
    eng = StreamEngine(mode="memory")
    proc = StreamProcessor(eng, window_seconds=60)
    proc.start()
    try:
        eng.publish(TOPIC_NEWS_RAW, "n1", {"title": "公司净利润增长超预期，回购股份"})
        eng.publish(TOPIC_NEWS_RAW, "n1", {"title": "公司净利润增长超预期，回购股份"})  # dup
        for _ in range(30):
            time.sleep(0.1)
            if proc.duplicates_skipped >= 1:
                break
        assert proc.duplicates_skipped >= 1
        s = eng.stats()
        assert s[TOPIC_NEWS_PROCESSED]["published"] >= 1
        with _db_conn() as c:
            row = c.execute("SELECT sentiment FROM news_cache LIMIT 1").fetchone()
        assert row and row["sentiment"] in ("利好", "利空", "中性")
    finally:
        proc.stop()


def test_processor_tick_window_agg():
    with _db_conn() as c:  # 清理历史残留，保证断言确定性
        c.execute("DELETE FROM tick_cache")
    eng = StreamEngine(mode="memory")
    proc = StreamProcessor(eng, window_seconds=300)
    proc.start()
    try:
        for v in (100, 200, 300):
            eng.publish(TOPIC_MARKET_TICK, "600519",
                        {"code": "600519", "price": 1700 + v, "volume": v})
        # 轮询等待消费线程落库（最多 3 秒）
        n = 0
        for _ in range(30):
            time.sleep(0.1)
            with _db_conn() as c:
                n = c.execute("SELECT COUNT(*) n FROM tick_cache WHERE code='600519'").fetchone()["n"]
            if n == 3:
                break
        assert n == 3, f"tick 缓存应有 3 条，实际 {n}"
        # 窗口聚合直接验证
        proc._window_push(TOPIC_MARKET_TICK, "600519", 100)
        proc._window_push(TOPIC_MARKET_TICK, "600519", 200)
        agg = proc._window_agg(TOPIC_MARKET_TICK, "600519")
        assert agg and agg["count"] == 5 and agg["mean"] > 0
    finally:
        proc.stop()


def test_processor_filing_ai_parser():
    eng = StreamEngine(mode="memory")
    proc = StreamProcessor(eng)
    proc.start()
    calls = []

    def fake_ai(f):
        calls.append(f["title"])
        return "摘要卡片已生成"

    proc.filing_ai_parser = fake_ai
    try:
        eng.publish(TOPIC_FILINGS_NEW, "f1", {"title": "重大合同公告", "code": "000001"})
        for _ in range(30):
            time.sleep(0.1)
            if calls:
                break
        assert calls, "AI 解析回调应被调用"
    finally:
        proc.stop()


def test_memory_backend_poll():
    b = _MemoryBackend()
    b.publish(TOPIC_NEWS_RAW, "x", {"a": 1})
    msg = b.poll(TOPIC_NEWS_RAW, timeout=0.2)
    assert msg and msg["key"] == "x"
    assert b.poll(TOPIC_NEWS_RAW, timeout=0.05) is None


def test_msg_id_deterministic():
    assert _msg_id("k", {"a": 1}) == _msg_id("k", {"a": 1})
    assert _msg_id("k", {"a": 1}) != _msg_id("k", {"a": 2})


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"[ok] {fn.__name__}")
    print(f"\nALL PASS ({len(fns)})")
