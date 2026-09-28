# -*- coding: utf-8 -*-
"""微前端 Shell：模块注册、挂载/卸载、事件总线、生命周期协调。"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field

log = logging.getLogger("stockai.micro_frontend.shell")


class EventBus:
    """轻量发布-订阅事件总线（线程安全）。"""

    def __init__(self):
        self._subs: dict[str, list] = {}
        self._lock = threading.Lock()

    def on(self, event: str, fn) -> None:
        with self._lock:
            self._subs.setdefault(event, []).append(fn)

    def emit(self, event: str, payload: dict | None = None) -> int:
        with self._lock:
            fns = list(self._subs.get(event, []))
        for fn in fns:
            try:
                fn(payload or {})
            except Exception as e:  # noqa: BLE001
                log.warning("事件 %s 处理失败: %s", event, e)
        return len(fns)


@dataclass
class ModuleContext:
    """模块运行上下文：事件总线 + 配置 + 安全层句柄。"""
    bus: EventBus
    config: dict = field(default_factory=dict)
    security: object = None
    env: dict = field(default_factory=dict)


class MicroFrontendShell:
    """微前端 Shell：注册/挂载/卸载/协调各功能模块。"""

    def __init__(self, name: str = "shuying-shell"):
        self.name = name
        self.bus = EventBus()
        self.modules: dict[str, object] = {}
        self.mounted: dict[str, object] = {}
        self.context = ModuleContext(bus=self.bus)
        self._registry: dict[str, dict] = {}

    def register(self, module: object, *, version: str = "1.0",
                 capabilities: list | None = None) -> None:
        """注册模块（接口：.name / .mount(ctx, container) / .unmount() / .ping()）。"""
        name = module.name
        self.modules[name] = module
        self._registry[name] = {"version": version,
                                "capabilities": capabilities or [],
                                "registered_at": time.time()}
        self.bus.emit("module:registered", {"name": name})

    def unregister(self, name: str) -> bool:
        if name not in self.modules:
            return False
        if name in self.mounted:
            self.unmount(name)
        del self.modules[name]
        self._registry.pop(name, None)
        self.bus.emit("module:unregistered", {"name": name})
        return True

    def mount(self, name: str, container=None) -> bool:
        """挂载模块到容器（PyQt 场景下 container 为 QWidget/QVBoxLayout 等）。"""
        mod = self.modules.get(name)
        if mod is None:
            return False
        try:
            result = mod.mount(self.context, container)
            self.mounted[name] = result
            self.bus.emit("module:mounted", {"name": name})
            return True
        except Exception as e:  # noqa: BLE001
            log.warning("挂载模块 %s 失败: %s", name, e)
            return False

    def unmount(self, name: str) -> bool:
        mod = self.modules.get(name)
        if mod is None or name not in self.mounted:
            return False
        try:
            mod.unmount()
        except Exception as e:  # noqa: BLE001
            log.warning("卸载模块 %s 异常: %s", name, e)
        self.mounted.pop(name, None)
        self.bus.emit("module:unmounted", {"name": name})
        return True

    def ping(self, name: str) -> bool:
        mod = self.modules.get(name)
        if mod is None:
            return False
        try:
            return bool(mod.ping())
        except Exception:  # noqa: BLE001
            return False

    def list_modules(self) -> list[dict]:
        out = []
        for name, reg in self._registry.items():
            out.append({"name": name, "version": reg["version"],
                        "capabilities": reg["capabilities"],
                        "mounted": name in self.mounted})
        return out

    def mount_all(self, container_map: dict | None = None) -> int:
        """批量挂载（container_map: {module_name: container}）。"""
        n = 0
        for name in list(self.modules):
            container = (container_map or {}).get(name)
            if self.mount(name, container):
                n += 1
        return n

    def stats(self) -> dict:
        return {"registered": len(self.modules), "mounted": len(self.mounted),
                "events_subscribed": sum(len(v) for v in self.bus._subs.values())}


if __name__ == "__main__":
    from micro_frontend.modules import KLineModule, DebateModule

    shell = MicroFrontendShell()
    shell.register(KLineModule(), version="1.0", capabilities=["chart"])
    shell.register(DebateModule(), version="1.0", capabilities=["debate"])
    assert not shell.ping("kline") and not shell.ping("debate")   # 未挂载
    assert shell.mount("kline") and shell.mount("debate")
    assert shell.ping("kline") and shell.ping("debate")
    assert len(shell.mounted) == 2
    fired = []

    def _on(ev):
        fired.append(ev)

    shell.bus.on("custom:evt", _on)
    shell.bus.emit("custom:evt", {"x": 1})
    assert fired
    assert shell.unmount("kline") and not shell.ping("kline")
    assert len(shell.list_modules()) == 2
    print(f"PASS micro_frontend.shell 自测 {shell.stats()}")
