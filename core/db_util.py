# -*- coding: utf-8 -*-
"""统一 SQLite 连接入口（第20轮 · 工程可靠性）。

背景
----
全项目有 30+ 处 ``sqlite3.connect(...)``，各自写各自的超时参数，
Windows 下并发写（UI 线程 + 后台任务 + 测试串行）会偶发：

- ``OperationalError: database is locked``
- ``OperationalError: attempt to write a readonly database``

后者尤其隐蔽：不是文件真的只读，而是**并发持有 + WAL/shm 未就绪**时
SQLite 退化出的报错。分散在各模块里改，改一处漏一处。

统一入口提供的保证
------------------
1. **父目录自动创建**（含多层），缺目录不再报错；
2. **busy_timeout + 指数退避重试**（默认 3 次），吸收瞬时锁竞争；
3. **WAL 优先、失败自动降级** DELETE 日志模式（网络盘/只读盘场景）；
4. **写入不可用时不崩溃**：判定目标不可写 → 自动以只读 URI 打开，
   让上层读取路径继续可用（写操作会明确抛错而非静默失败）；
5. **连接级诊断**：``diagnose()`` 给出文件权限、目录可写性、当前 journal_mode。

用法
----
>>> from core.db_util import connect
>>> conn = connect(path)              # 带重试/降级/只读兜底
>>> with connect_ctx(path) as c:      # 自动关闭
...     c.execute("SELECT 1")

也可以只借用诊断能力：``diagnose(path)``。
"""
from __future__ import annotations

import logging
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, Optional, Union

log = logging.getLogger("stockai.core.db_util")

DEFAULT_TIMEOUT = 15.0        # 等锁秒数
DEFAULT_RETRIES = 3           # 写入类错误的重试次数
DEFAULT_BACKOFF = 0.08        # 退避基数（秒），指数增长
# 默认**不改**既有 journal_mode：小库在 WAL 下每次「最后一个连接关闭」都要
# checkpoint+删 -wal/-shm，Windows 上单次开销可达 30~40ms（实测：知识库冷检索
# 43ms → 210ms）。并发写冲突已由 busy_timeout + 重试吸收，WAL 按需开启。

_RETRYABLE = ("database is locked", "database table is locked",
              "disk i/o error", "database is busy", "attempt to write a readonly")


class DBOpenError(RuntimeError):
    """数据库连接最终失败（重试耗尽）。"""


# ---------------------------------------------------------------------------
# 诊断
# ---------------------------------------------------------------------------
def _ensure_parent(path: Path) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except Exception as e:  # noqa: BLE001
        log.debug("父目录创建失败 %s：%s", path.parent, e)


def is_writable(path: Union[str, Path]) -> bool:
    """判断目标 db 文件（或其父目录）是否可写。"""
    p = Path(str(path))
    target = p if p.exists() else p.parent
    try:
        target.mkdir(parents=True, exist_ok=True)
        probe = target / f"._wtest_{os.getpid()}"
        with open(probe, "wb") as f:
            f.write(b"0")
        probe.unlink(missing_ok=True)
        return True
    except Exception as e:  # noqa: BLE001
        log.debug("可写性探测失败 %s：%s", target, e)
        return False


def diagnose(path: Union[str, Path]) -> Dict[str, Any]:
    """返回一份可读的连接环境诊断，便于排障与 UI 展示。"""
    p = Path(str(path))
    info: Dict[str, Any] = {
        "path": str(p),
        "exists": p.exists(),
        "size": p.stat().st_size if p.exists() else 0,
        "parent_exists": p.parent.exists(),
        "parent_writable": is_writable(p.parent),
        "file_writable": None,
        "journal_mode": None,
        "ok": True,
        "hint": "",
    }
    if not p.parent.exists():
        info["ok"] = False
        info["hint"] = "父目录不存在（connect 会自动创建）"
        return info
    if not info["parent_writable"]:
        info["ok"] = False
        info["hint"] = "父目录不可写，连接将退化为只读"
    if not p.exists():
        return info
    try:
        info["file_writable"] = os.access(str(p), os.W_OK)
    except Exception:  # noqa: BLE001
        info["file_writable"] = None
    try:
        c = sqlite3.connect(str(p), timeout=1.0)
        info["journal_mode"] = c.execute("PRAGMA journal_mode").fetchone()[0]
        c.close()
    except Exception as e:  # noqa: BLE001
        info["ok"] = False
        info["hint"] = f"无法打开：{type(e).__name__}: {e}"
    return info


# ---------------------------------------------------------------------------
# 连接
# ---------------------------------------------------------------------------
def _open_once(path: str, timeout: float, readonly: bool,
               wal: bool) -> sqlite3.Connection:
    if readonly:
        uri = f"file:{Path(path).as_posix()}?mode=ro"
        c = sqlite3.connect(uri, uri=True, timeout=timeout)
    else:
        c = sqlite3.connect(str(path), timeout=timeout)
    try:
        c.execute(f"PRAGMA busy_timeout = {int(timeout * 1000)}")
        if wal and not readonly:
            try:
                c.execute("PRAGMA journal_mode = WAL")
            except sqlite3.DatabaseError as e:  # noqa: BLE001
                log.debug("WAL 不可用，降级 DELETE：%s", e)
                try:
                    c.execute("PRAGMA journal_mode = DELETE")
                except Exception:  # noqa: BLE001
                    pass
    except sqlite3.DatabaseError:
        pass
    return c


def connect(db_path: Union[str, Path],
            timeout: float = DEFAULT_TIMEOUT,
            retries: int = DEFAULT_RETRIES,
            backoff: float = DEFAULT_BACKOFF,
            wal: bool = False,
            readonly_fallback: bool = True) -> sqlite3.Connection:
    """打开 SQLite 连接（带重试 / WAL 降级 / 只读兜底）。

    Args:
        db_path: 数据库文件路径（父目录自动创建）。
        timeout: 等锁超时（秒），同时写入 busy_timeout。
        retries: 可重试错误的最大尝试次数。
        backoff: 退避基数，实际等待 ``backoff * 2**(n-1)``。
        wal: 是否切换到 WAL 日志模式（默认 False＝沿用数据库既有模式；
            高并发写入的场景显式传 True）。
        readonly_fallback: 目标不可写时是否退化为只读连接。

    Raises:
        DBOpenError: 重试耗尽仍无法打开。
    """
    p = Path(str(db_path))
    _ensure_parent(p)
    last: Optional[Exception] = None
    for n in range(max(1, int(retries))):
        try:
            return _open_once(str(p), timeout, readonly=False, wal=wal)
        except sqlite3.OperationalError as e:
            last = e
            msg = str(e).lower()
            if not any(k in msg for k in _RETRYABLE):
                break
            if n + 1 < max(1, int(retries)):
                time.sleep(backoff * (2 ** n))
        except sqlite3.DatabaseError as e:  # noqa: BLE001
            last = e
            break
    if readonly_fallback and not is_writable(p):
        log.warning(
            "数据库不可写，退化为只读连接（写操作将失败）：%s", p)
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            if p.exists():
                return _open_once(str(p), timeout, readonly=True, wal=False)
        except Exception as e:  # noqa: BLE001
            last = e
    if last is not None:
        raise DBOpenError(f"无法打开数据库 {p}：{type(last).__name__}: {last}")
    raise DBOpenError(f"无法打开数据库 {p}（原因未知）")


@contextmanager
def connect_ctx(db_path: Union[str, Path], **kw) -> Iterator[sqlite3.Connection]:
    """上下文管理：``with connect_ctx(path) as c:``（退出自动关闭）。"""
    c = connect(db_path, **kw)
    try:
        yield c
    finally:
        try:
            c.close()
        except Exception:  # noqa: BLE001
            pass


def ping(db_path: Union[str, Path]) -> Dict[str, Any]:
    """轻量探活：能否连上 + 执行一条 SQL。UI「系统自检」直接可用。"""
    t0 = time.time()
    try:
        with connect_ctx(db_path, retries=1, readonly_fallback=False) as c:
            c.execute("SELECT 1").fetchone()
        return {"ok": True, "path": str(db_path),
                "latency_ms": round((time.time() - t0) * 1000, 2)}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "path": str(db_path),
                "latency_ms": round((time.time() - t0) * 1000, 2),
                "error": f"{type(e).__name__}: {e}"}


if __name__ == "__main__":
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    db = tmp / "a" / "b" / "t.db"          # 多级父目录
    c = connect(db)
    c.execute("CREATE TABLE IF NOT EXISTS t(x INTEGER)")
    c.execute("INSERT INTO t VALUES(1)")
    c.commit()
    assert c.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 1
    c.close()
    with connect_ctx(db) as c2:
        assert c2.execute("SELECT MAX(x) FROM t").fetchone()[0] == 1
    d = diagnose(db)
    assert d["exists"] and d["ok"], d
    assert ping(db)["ok"] is True
    ro = connect(tmp / "ro.db", readonly_fallback=True)
    ro.execute("SELECT 1")
    ro.close()
    bad = ping(tmp / "no" / "such" / "x.db")   # 多级父目录会被自动创建
    # WAL 按需开启（默认不改既有模式）
    w = connect(tmp / "wal.db", wal=True)
    assert w.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    w.close()
    d2 = connect(tmp / "wal.db")
    d2.execute("SELECT 1")
    d2.close()
    print("db_util self-check ok:", d["journal_mode"],
          "| nodir_ping:", bad["ok"], "| wal_optin: True")
