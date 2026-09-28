# -*- coding: utf-8 -*-
"""模型注册表（BYOM：客户自带模型）。

支持三类端点：
  - local: 本地权重目录（如 models/Qwen2.5-3B-Instruct/）
  - ollama: http://localhost:11434（模型名）
  - openai: OpenAI 兼容 API（base_url + api_key + model）

提供 resolve() 统一解析为调用配置；未配置时返回 None（由上层降级）。
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field

log = logging.getLogger("stockai.sovereign.models")


@dataclass
class ModelEntry:
    name: str
    kind: str            # local / ollama / openai
    endpoint: str = ""   # 本地路径 / ollama host / base_url
    model: str = ""      # ollama 模型名 / openai model id
    api_key: str = ""    # openai 类型必填
    status: str = "untested"
    note: str = ""
    extra: dict = field(default_factory=dict)

    def resolve(self) -> dict | None:
        """解析为调用配置；缺关键字段返回 None。"""
        if self.kind == "local":
            import os
            if not self.endpoint or not os.path.isdir(self.endpoint):
                return None
            return {"kind": "local", "path": self.endpoint}
        if self.kind == "ollama":
            return {"kind": "ollama", "host": self.endpoint or "http://localhost:11434",
                    "model": self.model}
        if self.kind == "openai":
            if not self.api_key:
                return None
            return {"kind": "openai", "base_url": self.endpoint or "https://api.openai.com/v1",
                    "model": self.model, "api_key": self.api_key}
        return None


class ModelRegistry:
    """BYOM 模型注册表（线程安全）。"""

    def __init__(self):
        self._lock = threading.Lock()
        self._models: dict[str, ModelEntry] = {}

    def register(self, entry: ModelEntry) -> None:
        with self._lock:
            self._models[entry.name] = entry

    def register_openai_compatible(self, name: str, base_url: str, model: str,
                                   api_key: str = "") -> ModelEntry:
        e = ModelEntry(name=name, kind="openai", endpoint=base_url,
                       model=model, api_key=api_key)
        self.register(e)
        return e

    def register_local(self, name: str, path: str) -> ModelEntry:
        e = ModelEntry(name=name, kind="local", endpoint=path)
        self.register(e)
        return e

    def register_ollama(self, name: str, model: str, host: str = "http://localhost:11434") -> ModelEntry:
        e = ModelEntry(name=name, kind="ollama", endpoint=host, model=model)
        self.register(e)
        return e

    def resolve(self, name: str) -> dict | None:
        e = self._models.get(name)
        return e.resolve() if e else None

    def list(self) -> list[dict]:
        with self._lock:
            return [{"name": n, "kind": e.kind, "model": e.model,
                     "status": e.status, "note": e.note}
                    for n, e in self._models.items()]

    def test(self, name: str) -> bool:
        """连通性自检：local 检查目录存在；ollama/openai 检查端点可达（超时短）。"""
        e = self._models.get(name)
        if e is None:
            return False
        cfg = e.resolve()
        if cfg is None:
            e.status = "misconfigured"
            return False
        try:
            if cfg["kind"] == "local":
                import os
                ok = os.path.isdir(cfg["path"])
            else:
                import urllib.request
                host = cfg.get("host") or cfg.get("base_url", "")
                url = host.rstrip("/") + "/v1/models" if "api" in host else host
                req = urllib.request.Request(url, method="GET")
                urllib.request.urlopen(req, timeout=3)  # noqa: S310
                ok = True
            e.status = "ok" if ok else "unreachable"
            return ok
        except Exception as ex:  # noqa: BLE001
            e.status = "unreachable"
            e.note = str(ex)[:120]
            return False


_default_registry = ModelRegistry()


def registry() -> ModelRegistry:
    return _default_registry


if __name__ == "__main__":
    reg = ModelRegistry()
    reg.register_local("qwen-3b", "models/__no_such_model_dir__")
    reg.register_openai_compatible("deepseek", "https://api.deepseek.com/v1", "deepseek-chat")
    reg.register_ollama("qwen-ollama", "qwen3:7b")
    assert reg.list()
    assert reg.resolve("deepseek") is None           # openai 无 key → None
    assert reg.resolve("qwen-3b") is None            # 目录不存在 → None
    assert reg.resolve("qwen-ollama") is not None    # ollama 恒可解析
    assert not reg.test("qwen-3b")
    print("PASS model_registry 自测（local 降级、openai 缺 key 降级、ollama 注册）")
