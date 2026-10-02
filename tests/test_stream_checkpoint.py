# -*- coding: utf-8 -*-
"""实时管道锚点持久化 + 断点续传 + 5秒滚动窗口测试。"""
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("STOCKAI_MOCK", "1")


def _store(td):
    from streaming.stream_checkpoint import CheckpointStore
    return CheckpointStore(Path(td) / "cp.db")


class TestCheckpointStore(unittest.TestCase):
    def test_anchor_monotonic(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            s = _store(td)
            self.assertIsNone(s.get_anchor("market.tick"))
            s.set_anchor("market.tick", 100.0)
            self.assertEqual(s.get_anchor("market.tick"), 100.0)
            s.set_anchor("market.tick", 200.0)
            self.assertEqual(s.get_anchor("market.tick"), 200.0)
            # 锚点不允许回拨
            s.set_anchor("market.tick", 150.0)
            self.assertEqual(s.get_anchor("market.tick"), 200.0)

    def test_idempotent_mark(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            s = _store(td)
            self.assertTrue(s.mark_processed("news.raw", "n1"))
            self.assertFalse(s.mark_processed("news.raw", "n1"))  # 重复
            self.assertTrue(s.is_processed("news.raw", "n1"))
            self.assertFalse(s.is_processed("news.raw", "n2"))
            # topic 隔离
            self.assertTrue(s.mark_processed("market.tick", "n1"))

    def test_persistence_across_instances(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            s1 = _store(td)
            s1.set_anchor("market.tick", 123.0)
            s1.mark_processed("market.tick", "m1")
            # 模拟进程重启：新实例读同一 DB
            s2 = _store(td)
            self.assertEqual(s2.get_anchor("market.tick"), 123.0)
            self.assertTrue(s2.is_processed("market.tick", "m1"))


class TestResumeManager(unittest.TestCase):
    def test_resume_from_anchor(self):
        from streaming.stream_checkpoint import ResumeManager
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            rm = ResumeManager(_store(td), max_backfill_seconds=3600)
            now = time.time()
            # 无锚点 → now - max_backfill
            self.assertAlmostEqual(rm.resume_from("t", now=now), now - 3600)
            # 有锚点 → 从锚点续传
            rm.store.set_anchor("t", now - 100)
            self.assertAlmostEqual(rm.resume_from("t", now=now), now - 100)
            # 离线过久 → 补数窗口封顶
            rm.store.set_anchor("t", now - 7200)  # 锚点回拨无效，仍为 now-100
            self.assertAlmostEqual(rm.resume_from("t", now=now), now - 100)

    def test_backfill_no_dup_no_loss(self):
        from streaming.stream_checkpoint import ResumeManager
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            rm = ResumeManager(_store(td))
            now = time.time()
            for i in range(3):
                self.assertTrue(rm.should_process("t", f"m{i}", now - 100 + i))
            self.assertFalse(rm.should_process("t", "m1", now - 99))  # 重复
            got = []
            stats = rm.backfill("t", [
                {"id": "m2", "ts": now - 98},   # 已处理
                {"id": "m3", "ts": now - 50},   # 新
                {"id": "m4", "ts": now - 40},   # 新
                {"id": "m3", "ts": now - 50},   # 重复投递
            ], got.append)
            self.assertEqual(stats["processed"], 2)
            self.assertEqual([m["id"] for m in got], ["m3", "m4"])
            self.assertEqual(stats["skipped_duplicates"], 1)


class TestTumblingWindow(unittest.TestCase):
    def test_five_second_tumbling(self):
        from streaming.stream_checkpoint import TumblingWindow
        closed = []
        tw = TumblingWindow(5, on_window_close=closed.append)
        base = 1_700_000_000.0
        tw.push("600519", 100.0, ts=base + 0.5)
        tw.push("600519", 102.0, ts=base + 1.0)
        self.assertEqual(closed, [])
        tw.push("600519", 105.0, ts=base + 6.0)  # 跨窗口 → 关闭前窗
        self.assertEqual(len(closed), 1)
        w = closed[0]
        self.assertEqual(w["count"], 2)
        self.assertEqual(w["mean"], 101.0)
        self.assertEqual(w["min"], 100.0)
        self.assertEqual(w["max"], 102.0)
        self.assertEqual(w["window_end"] - w["window_start"], 5)

    def test_flush(self):
        from streaming.stream_checkpoint import TumblingWindow
        tw = TumblingWindow(5)
        base = 1_700_000_000.0
        tw.push("A", 1.0, ts=base)
        tw.push("A", 3.0, ts=base + 1)
        rest = tw.flush()
        self.assertEqual(len(rest), 1)
        self.assertEqual(rest[0]["mean"], 2.0)
        self.assertEqual(tw.flush(), [])  # 再次 flush 为空

    def test_invalid_window(self):
        from streaming.stream_checkpoint import TumblingWindow
        with self.assertRaises(ValueError):
            TumblingWindow(0)


class TestStreamProcessorCheckpointIntegration(unittest.TestCase):
    def test_processor_persistent_dedup(self):
        """StreamProcessor 挂载 checkpoint 后，重启（新实例）仍能幂等去重。"""
        from streaming.stream_engine import StreamEngine, StreamProcessor
        from streaming.stream_checkpoint import CheckpointStore
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            store = CheckpointStore(Path(td) / "cp.db")
            eng = StreamEngine(mode="memory")
            p1 = StreamProcessor(eng, window_seconds=60, checkpoint=store)
            r1 = p1.process_tick({"id": "t1", "code": "600519",
                                  "price": 1700.0, "volume": 100, "ts": 1000.0})
            self.assertNotIn("skipped", r1)
            # 新处理器实例（模拟重启），内存 _seen 为空，但持久层记得
            p2 = StreamProcessor(eng, window_seconds=60, checkpoint=store)
            r2 = p2.process_tick({"id": "t1", "code": "600519",
                                  "price": 1700.0, "volume": 100, "ts": 1000.0})
            self.assertTrue(r2.get("skipped"))
            # 锚点已推进
            self.assertEqual(store.get_anchor("market.tick"), 1000.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
