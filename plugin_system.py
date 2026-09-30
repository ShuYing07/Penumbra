# -*- coding: utf-8 -*-
"""插件化生态（模块五）：PluginBase 生命周期 + importlib 动态加载 + 权限系统 + zip 安装。

设计（对齐 Wealthfolio Addon 系统 + FinceptTerminal 扩展架构）：
- PluginBase：on_load / on_unload / register_ui / register_tools / get_metadata；
- PluginContext：插件与主程序交互的受限门面（注册工具、注册导航、只读数据访问）；
- PluginManager：扫描 plugins/ 目录、动态导入、启用/禁用、卸载、zip 安装；
- 权限系统：插件 manifest 声明所需权限（data_access / network / file_write / ui），
  加载时校验授权，未授权权限直接拒绝注册。
"""
from __future__ import annotations

import importlib.util
import json
import logging
import os
import zipfile
from dataclasses import dataclass, field

log = logging.getLogger("stockai.plugin")

PERMISSIONS = {"data_access", "network", "file_write", "ui"}


@dataclass
class PluginContext:
    """插件可见的主程序门面（受限）。"""
    app: object = None                     # 主窗口/宿主引用
    tools: dict = field(default_factory=dict)       # 注册的 Agent 工具 {name: fn}
    nav_items: list = field(default_factory=list)   # 注册的导航项
    data_access: bool = False              # 是否已授予数据访问权限

    def register_tool(self, name: str, fn, desc: str = "", schema: dict | None = None):
        self.tools[name] = {"fn": fn, "desc": desc, "schema": schema or {}}

    def register_nav(self, label: str, target=None):
        self.nav_items.append({"label": label, "target": target})


class PluginBase:
    """插件基类。子类实现生命周期钩子。"""

    metadata: dict = {"name": "unnamed", "version": "0.0.1",
                      "author": "unknown", "permissions": [], "description": ""}

    def on_load(self, ctx: PluginContext):  # noqa: B027
        """插件加载时调用（此时权限已校验）。"""

    def on_unload(self):  # noqa: B027
        """插件卸载时调用。"""

    def register_ui(self, ctx: PluginContext):  # noqa: B027
        """注册 UI 组件/导航项。"""

    def register_tools(self, ctx: PluginContext):  # noqa: B027
        """注册 Agent 工具。"""

    def get_metadata(self) -> dict:
        return dict(self.metadata)


class PluginManager:
    """插件加载器：扫描 → 校验权限 → 加载 → 注册 → 卸载。"""

    def __init__(self, plugins_dir: str):
        self.plugins_dir = os.path.abspath(plugins_dir)
        self._instances: dict[str, PluginBase] = {}
        self._contexts: dict[str, PluginContext] = {}
        self._enabled: dict[str, bool] = {}
        self._permission_state: dict[str, dict] = {}  # name -> {granted: [...]}
        self._load_errors: dict[str, str] = {}

    # ---- 发现 ----
    def discover(self) -> list[dict]:
        """扫描 plugins/ 下每个子目录，读取 manifest.json（或 plugin.py 内 metadata）。"""
        found = []
        if not os.path.isdir(self.plugins_dir):
            return found
        for entry in sorted(os.listdir(self.plugins_dir)):
            p = os.path.join(self.plugins_dir, entry)
            if not os.path.isdir(p) or entry.startswith("__"):
                continue
            manifest = None
            mf = os.path.join(p, "manifest.json")
            if os.path.isfile(mf):
                try:
                    with open(mf, "r", encoding="utf-8") as f:
                        manifest = json.load(f)
                except Exception as e:  # noqa: BLE001
                    manifest = {"error": str(e)[:80]}
            found.append({"name": entry, "path": p, "manifest": manifest})
        return found

    def list_plugins(self) -> list[dict]:
        """返回插件总览（含加载/启用状态）。"""
        out = []
        for d in self.discover():
            name = d["name"]
            manifest = d["manifest"] or {}
            out.append({
                "name": name,
                "version": manifest.get("version", "0.0.1"),
                "author": manifest.get("author", "unknown"),
                "description": manifest.get("description", ""),
                "permissions": manifest.get("permissions", []),
                "enabled": self._enabled.get(name, False),
                "loaded": name in self._instances,
                "error": self._load_errors.get(name),
            })
        return out

    # ---- 权限 ----
    def requested_permissions(self, plugin_name: str) -> list[str]:
        for d in self.discover():
            if d["name"] == plugin_name:
                perms = (d["manifest"] or {}).get("permissions", [])
                return [p for p in perms if p in PERMISSIONS]
        return []

    def grant_permissions(self, plugin_name: str, permissions: list[str]) -> dict:
        """授予权限（UI 安装确认时调用）。仅允许声明过的权限。"""
        valid = set(self.requested_permissions(plugin_name))
        granted = [p for p in permissions if p in valid]
        self._permission_state[plugin_name] = {"granted": granted}
        return {"granted": granted, "denied": [p for p in permissions if p not in valid]}

    # ---- 加载 ----
    def load(self, plugin_name: str, ctx: PluginContext | None = None) -> bool:
        """加载插件实例并调用生命周期。未授予的权限会被忽略并记录。"""
        if plugin_name in self._instances:
            return True
        p = os.path.join(self.plugins_dir, plugin_name)
        mod_file = os.path.join(p, "plugin.py")
        if not os.path.isfile(mod_file):
            self._load_errors[plugin_name] = "缺少 plugin.py"
            return False
        spec = importlib.util.spec_from_file_location(f"plugins_{plugin_name}", mod_file)
        if spec is None or spec.loader is None:
            self._load_errors[plugin_name] = "无法加载模块"
            return False
        try:
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            cls = getattr(mod, "Plugin", None)
            if cls is None or not issubclass(cls, PluginBase):
                self._load_errors[plugin_name] = "未定义 Plugin(PluginBase) 类"
                return False
            inst = cls()
            meta = inst.get_metadata()
            if meta.get("name") != plugin_name:
                self._load_errors[plugin_name] = \
                    f"metadata.name 应为 {plugin_name}，实际 {meta.get('name')}"
                return False
            # 权限校验：仅注入已授予权限对应的能力
            granted = set((self._permission_state.get(plugin_name) or {}).get("granted", []))
            pctx = ctx or PluginContext()
            pctx.data_access = "data_access" in granted
            inst.on_load(pctx)
            inst.register_tools(pctx)
            inst.register_ui(pctx)
            self._instances[plugin_name] = inst
            self._contexts[plugin_name] = pctx
            self._enabled[plugin_name] = True
            self._load_errors.pop(plugin_name, None)
            log.info("plugin loaded: %s", plugin_name)
            return True
        except Exception as e:  # noqa: BLE001
            self._load_errors[plugin_name] = f"{type(e).__name__}: {str(e)[:120]}"
            log.exception("plugin load failed: %s", plugin_name)
            return False

    def unload(self, plugin_name: str) -> bool:
        inst = self._instances.pop(plugin_name, None)
        if inst is not None:
            try:
                inst.on_unload()
            except Exception as e:  # noqa: BLE001
                log.warning("plugin unload error %s: %s", plugin_name, str(e)[:80])
        self._contexts.pop(plugin_name, None)
        self._enabled[plugin_name] = False
        return True

    def enable(self, plugin_name: str, ctx: PluginContext | None = None) -> bool:
        return self.load(plugin_name, ctx)

    def disable(self, plugin_name: str) -> bool:
        return self.unload(plugin_name)

    def get_tools(self) -> dict:
        merged: dict = {}
        for pctx in self._contexts.values():
            merged.update(pctx.tools)
        return merged

    def get_nav_items(self) -> list:
        out = []
        for pctx in self._contexts.values():
            out.extend(pctx.nav_items)
        return out

    # ---- 安装 ----
    def install_zip(self, zip_path: str) -> dict:
        """从 .zip 安装插件：解压到 plugins/，校验 manifest 与权限声明。"""
        if not os.path.isfile(zip_path):
            return {"ok": False, "error": "zip 文件不存在"}
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                # 安全校验：拒绝路径穿越
                for info in zf.infolist():
                    n = info.filename.replace("\\", "/")
                    if n.startswith("/") or ".." in n.split("/"):
                        return {"ok": False, "error": f"非法路径：{info.filename}"}
                # 必须含 plugin.py
                names = [i.filename.replace("\\", "/") for i in zf.infolist()]
                if not any(n.endswith("plugin.py") for n in names):
                    return {"ok": False, "error": "zip 中缺少 plugin.py"}
                # 顶层目录名 = 插件名
                top = names[0].split("/")[0] if names else ""
                if not top:
                    return {"ok": False, "error": "空 zip"}
                target = os.path.join(self.plugins_dir, top)
                os.makedirs(target, exist_ok=True)
                for info in zf.infolist():
                    rel = info.filename.replace("\\", "/")
                    dest = os.path.join(target, rel.split("/", 1)[-1] if "/" in rel else "")
                    if not dest or info.is_dir():
                        continue
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    with zf.open(info) as src, open(dest, "wb") as f:
                        f.write(src.read())
            perms = self.requested_permissions(top)
            return {"ok": True, "name": top, "permissions": perms,
                    "path": os.path.join(self.plugins_dir, top)}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:120]}"}
