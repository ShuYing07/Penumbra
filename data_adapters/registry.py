# -*- coding: utf-8 -*-
"""数据源适配器注册表：注册、发现、动态切换。"""
from __future__ import annotations

import logging
import threading

log = logging.getLogger("stockai.data_adapters.registry")


class AdapterRegistry:
    """适配器注册表（线程安全）。"""

    def __init__(self):
        self._lock = threading.Lock()
        self._adapters: dict[str, object] = {}
        self._active: str | None = None

    def register(self, adapter) -> None:
        with self._lock:
            self._adapters[adapter.name] = adapter
            if self._active is None:
                self._active = adapter.name

    def activate(self, name: str) -> bool:
        with self._lock:
            if name not in self._adapters:
                return False
            self._active = name
            return True

    def active(self):
        with self._lock:
            return self._adapters.get(self._active)

    def get(self, name: str):
        with self._lock:
            return self._adapters.get(name)

    def list(self) -> list[dict]:
        with self._lock:
            out = []
            for name, a in self._adapters.items():
                d = a.describe() if hasattr(a, "describe") else {"name": name}
                d["active"] = name == self._active
                out.append(d)
            return out

    def health_all(self) -> dict:
        out = {}
        with self._lock:
            items = list(self._adapters.items())
        for name, a in items:
            try:
                out[name] = a.health_check()
            except Exception as e:  # noqa: BLE001
                out[name] = {"ok": False, "note": str(e)[:100]}
        return out


_default = AdapterRegistry()


def get_registry() -> AdapterRegistry:
    return _default


def switch_source(name: str) -> bool:
    """切换当前数据源；未注册返回 False。"""
    return _default.activate(name)


def register_builtin_adapters() -> None:
    """注册内置适配器（akshare/yfinance 包装），供统一路由使用。"""
    from data_adapters.akshare_adapter import AkshareAdapter
    from data_adapters.yfinance_adapter import YFinanceAdapter
    _default.register(AkshareAdapter())
    _default.register(YFinanceAdapter())
    if _default.active() is None:
        _default.activate("akshare")


if __name__ == "__main__":
    register_builtin_adapters()
    reg = get_registry()
    assert reg.active() is not None
    assert len(reg.list()) >= 2
    print(f"PASS data_adapters.registry 自测 active={reg.active().name if reg.active() else None}")
