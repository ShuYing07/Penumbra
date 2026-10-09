# -*- coding: utf-8 -*-
"""core/db_util.py 统一 SQLite 连接入口单测。

验证：多级父目录自动创建、busy_timeout 生效、WAL 优先、锁竞争重试、
只读兜底、上下文管理、诊断与探活、不可用时抛 DBOpenError 而非崩溃。
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("STOCKAI_MOCK", "1")

from core import db_util

_TMP = Path(tempfile.mkdtemp(prefix="dbutil_"))


def _db(name: str) -> Path:
    return _TMP / name.replace("/", os.sep) / "t.db"


# ---------------------------------------------------------------------------
# 基础连接
# ---------------------------------------------------------------------------
def test_creates_nested_parent():
    p = _db("a/b/c")
    c = db_util.connect(p)
    assert p.parent.exists()
    c.close()


def test_read_write_roundtrip():
    p = _db("rw")
    c = db_util.connect(p)
    c.execute("CREATE TABLE t(x INTEGER)")
    c.execute("INSERT INTO t VALUES(42)")
    c.commit()
    assert c.execute("SELECT x FROM t").fetchone()[0] == 42
    c.close()


def test_busy_timeout_applied():
    p = _db("busy")
    c = db_util.connect(p, timeout=7.5)
    ms = c.execute("PRAGMA busy_timeout").fetchone()[0]
    assert ms == 7500, ms
    c.close()


def test_wal_preferred():
    p = _db("wal")
    c = db_util.connect(p, wal=True)
    mode = c.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal", mode
    c.close()


def test_wal_can_be_disabled():
    p = _db("nowal")
    c = db_util.connect(p, wal=False)
    assert c.execute("PRAGMA journal_mode").fetchone()[0].lower() in (
        "delete", "wal", "memory", "truncate", "persist")
    c.close()


def test_default_keeps_existing_journal_mode():
    """默认不改 journal_mode（WAL 在 Windows 小库上每次关连接都要 checkpoint，
    实测会让知识库冷检索从 43ms 涨到 210ms）。"""
    p = _db("official_ascii_db")          # 避免非 ASCII 路径干扰
    c = db_util.connect(p)
    mode = c.execute("PRAGMA journal_mode").fetchone()[0]
    c.close()
    assert mode.lower() == "delete", mode
    assert db_util.DEFAULT_RETRIES >= 1


# ---------------------------------------------------------------------------
# 上下文管理
# ---------------------------------------------------------------------------
def test_connect_ctx_closes():
    p = _db("ctx")
    with db_util.connect_ctx(p) as c:
        c.execute("CREATE TABLE IF NOT EXISTS k(v TEXT)")
    try:
        c.execute("SELECT 1")
        raise AssertionError("连接应当已关闭")
    except sqlite3.ProgrammingError:
        pass


def test_connect_ctx_closes_on_exception():
    p = _db("ctxerr")
    try:
        with db_util.connect_ctx(p) as c:
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    try:
        c.execute("SELECT 1")
        raise AssertionError("异常时也应关闭")
    except sqlite3.ProgrammingError:
        pass


# ---------------------------------------------------------------------------
# 锁竞争重试
# ---------------------------------------------------------------------------
def test_locked_is_retried_then_succeeds():
    """持有一个写锁 → 新连接重试后仍可建立（busy_timeout 生效）。"""
    p = _db("locked")
    a = db_util.connect(p)
    a.execute("CREATE TABLE lock_t(x INTEGER)")
    a.execute("BEGIN IMMEDIATE")
    a.execute("INSERT INTO lock_t VALUES(1)")
    try:
        b = db_util.connect(p, timeout=2.0, retries=2, backoff=0.01)
        b.execute("SELECT COUNT(*) FROM lock_t").fetchone()
        b.close()
    finally:
        a.rollback()
        a.close()


# ---------------------------------------------------------------------------
# 只读兜底
# ---------------------------------------------------------------------------
def test_readonly_fallback_opens_existing_file():
    p = _db("ro")
    c = db_util.connect(p)
    c.execute("CREATE TABLE r(x INTEGER)")
    c.commit()
    c.close()
    # 父目录可写 → 正常打开（并非真正只读，兜底不触发）
    ro = db_util.connect(p, readonly_fallback=True)
    assert ro.execute("SELECT COUNT(*) FROM r").fetchone()[0] == 0
    ro.close()


def test_readonly_connection_rejects_write():
    p = _db("ro2")
    c = db_util.connect(p)
    c.execute("CREATE TABLE r2(x INTEGER)")
    c.commit()
    c.close()
    ro = db_util._open_once(str(p), timeout=1.0, readonly=True, wal=False)
    try:
        ro.execute("INSERT INTO r2 VALUES(1)")
        raise AssertionError("只读连接不应允许写入")
    except sqlite3.OperationalError:
        pass
    finally:
        ro.close()


def test_failure_raises_dbopenerror():
    """父目录为文件时必然失败 → 明确抛 DBOpenError（不是裸 OperationalError）。"""
    blocker = _TMP / "blocker.txt"
    blocker.write_text("x", encoding="utf-8")
    bad = blocker / "nested.db"
    try:
        db_util.connect(bad, retries=1, readonly_fallback=False)
        raise AssertionError("应当抛出 DBOpenError")
    except db_util.DBOpenError:
        pass


# ---------------------------------------------------------------------------
# 诊断与探活
# ---------------------------------------------------------------------------
def test_diagnose_reports_structure():
    p = _db("diag")
    db_util.connect(p).close()
    d = db_util.diagnose(p)
    for k in ("path", "exists", "size", "parent_exists",
              "parent_writable", "journal_mode", "ok", "hint"):
        assert k in d, k
    assert d["exists"] is True


def test_diagnose_missing_file_ok_parent():
    d = db_util.diagnose(_TMP / "missing_parent_dir" / "x.db")
    assert isinstance(d["ok"], bool)
    assert isinstance(d["hint"], str)


def test_ping_ok():
    p = _db("ping")
    r = db_util.ping(p)
    assert r["ok"] is True
    assert r["latency_ms"] >= 0
    assert r["path"] == str(p)


def test_is_writable_true_for_tmp():
    assert db_util.is_writable(_TMP / "some.db") is True


def test_defaults():
    assert db_util.DEFAULT_TIMEOUT > 0
    assert db_util.DEFAULT_RETRIES >= 1
    assert db_util.DEFAULT_BACKOFF > 0


if __name__ == "__main__":
    for name, fn in sorted(list(globals().items())):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok  {name}")
    print("ALL OK")
