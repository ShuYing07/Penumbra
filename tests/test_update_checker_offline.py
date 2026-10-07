# -*- coding: utf-8 -*-
"""
更新检查 · 离线单元测试（第17轮·模块七）。

不依赖真实网络：通过 monkeypatch 注入 config_manager.check_update 的返回值，
验证 core/update_checker.py 的异步回调逻辑（有更新 / 无更新 / 异常静默失败）。
"""
import os
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

import core.update_checker as uc


class _Result:
    """后台线程回调的结果收集器（线程安全）。"""

    def __init__(self):
        self.value = None
        self.lock = threading.Lock()

    def set(self, v):
        with self.lock:
            self.value = v


def _run_async(monkeypatch, fake_return, raise_exc=None):
    """patch check_update 后触发一次异步检查，返回回调收集的结果。"""
    if raise_exc is not None:
        def _boom(*a, **k):
            raise raise_exc
        monkeypatch.setattr("config_manager.check_update", _boom)
    else:
        monkeypatch.setattr("config_manager.check_update", lambda *a, **k: fake_return)

    collector = _Result()

    def _cb(res):
        collector.set(res)

    uc.check_updates_async(on_result=_cb)
    # 后台 daemon 线程，最长等 2 秒
    deadline = time.time() + 2.0
    while time.time() < deadline and collector.value is None:
        time.sleep(0.02)
    return collector.value


def test_has_update(monkeypatch):
    """线上版本高于本地时，回调应收到 has_update=True。"""
    res = _run_async(monkeypatch, {
        "current": "0.9.0", "latest": "1.2.0",
        "has_update": True, "url": "https://x", "error": None,
    })
    assert res is not None, "回调未触发"
    assert res["has_update"] is True
    assert res["latest"] == "1.2.0"


def test_no_update(monkeypatch):
    """线上版本不高于本地时，回调应收到 has_update=False。"""
    res = _run_async(monkeypatch, {
        "current": "0.9.0", "latest": "0.9.0",
        "has_update": False, "url": "https://x", "error": None,
    })
    assert res is not None
    assert res["has_update"] is False


def test_network_error_is_silent(monkeypatch):
    """网络异常应静默失败（on_error 被调用，不抛异常到主线程）。"""
    errs = []
    monkeypatch.setattr("config_manager.check_update",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("timeout")))
    uc.check_updates_async(on_error=lambda e: errs.append(e))
    deadline = time.time() + 2.0
    while time.time() < deadline and not errs:
        time.sleep(0.02)
    assert errs, "异常场景未触发 on_error 回调"
    assert "timeout" in errs[0]