# -*- coding: utf-8 -*-
"""本地离线模型后端（Ollama）。

选型理由（详见知识库 02）：
- Ollama 自带打包 CUDA/CPU 运行库，Windows 一键安装，自动调度 GPU；
- 暴露 OpenAI 兼容端点（/v1/chat/completions），LLMRunner 可零成本切换；
- 默认模型 Qwen2.5-7B-Instruct Q4_K_M：中文金融语料训练充分、JSON 遵循度好，
  8GB 显存可放下（约 4.7GB）；低配置机器可退 3B（LOCAL_MODEL_SMALL）。
- 不把模型/推理引擎打进 exe（模型 4.7GB、Ollama 700MB+），改为运行时检测引导。
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

import requests

from core.config import LOCAL_MODEL, LOCAL_MODEL_SMALL, LOCAL_OLLAMA_URL

log = logging.getLogger("stockai.local")

INSTALL_URL = "https://ollama.com/download/windows"
_HEADERS = {"Content-Type": "application/json"}

# Ollama 永远在本机回环地址；必须绕过系统代理（Clash/v2ray 的环境变量
# 会把 127.0.0.1 也劫持到代理端口，导致连不到本机服务）。
SESSION = requests.Session()
SESSION.trust_env = False


# ---------- 安装与服务 ----------
def find_executable() -> str | None:
    """查找 ollama 可执行文件：PATH → 用户安装目录。"""
    path = os.environ.get("LOCALAPPDATA", "")
    candidates = [
        os.path.join(path, "Programs", "Ollama", "ollama.exe"),
        os.path.join(path, "Programs", "Ollama", "ollama"),
        "/usr/local/bin/ollama", "/opt/homebrew/bin/ollama",
    ]
    for c in candidates:
        if c and os.path.exists(c):
            return c
    # PATH 中查找
    from shutil import which

    return which("ollama")


def is_installed() -> bool:
    return find_executable() is not None


def is_running(timeout: float = 2.0) -> bool:
    try:
        r = SESSION.get(f"{LOCAL_OLLAMA_URL}/api/version", timeout=timeout)
        return r.status_code == 200
    except Exception:  # noqa: BLE001
        return False


def version() -> str | None:
    try:
        return SESSION.get(f"{LOCAL_OLLAMA_URL}/api/version", timeout=2).json().get("version")
    except Exception:  # noqa: BLE001
        return None


def ensure_started(wait_s: float = 30.0) -> bool:
    """确保 Ollama 服务在跑；装了没跑则后台拉起（桌面版装完通常已自启）。"""
    if is_running():
        return True
    exe = find_executable()
    if not exe:
        return False
    try:
        kwargs = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
        if sys.platform.startswith("win"):
            kwargs["creationflags"] = (subprocess.CREATE_NEW_PROCESS_GROUP
                                       | getattr(subprocess, "DETACHED_PROCESS", 0x00000008))
        subprocess.Popen([exe, "serve"], **kwargs)  # noqa: S603
    except Exception as e:  # noqa: BLE001
        log.warning("拉起 Ollama 服务失败：%s", e)
    deadline = time.time() + wait_s
    while time.time() < deadline:
        if is_running():
            return True
        time.sleep(1.0)
    return False


# ---------- 模型 ----------
def list_models() -> list[str]:
    try:
        r = SESSION.get(f"{LOCAL_OLLAMA_URL}/api/tags", timeout=5)
        return [m.get("name", "") for m in r.json().get("models", [])]
    except Exception:  # noqa: BLE001
        return []


def has_model(name: str = LOCAL_MODEL) -> bool:
    """Ollama 标签可能带 digest 后缀变体，按名称前缀匹配。"""
    target = name.split(":")[0]
    for m in list_models():
        if m == name or m.split(":")[0] == target:
            return True
    return False


def pull_model(name: str = LOCAL_MODEL, progress_cb=None) -> tuple[bool, str]:
    """拉取模型（流式 NDJSON）。progress_cb(pct:int 0-100| -1 不确定, status:str)。

    返回 (成功与否, 说明)。
    """
    try:
        with SESSION.post(f"{LOCAL_OLLAMA_URL}/api/pull",
                          json={"name": name, "stream": True},
                          headers=_HEADERS, stream=True, timeout=(10, 3600)) as r:
            if r.status_code != 200:
                return False, f"HTTP {r.status_code}: {r.text[:200]}"
            for line in r.iter_lines():
                if not line:
                    continue
                try:
                    msg = json.loads(line.decode("utf-8"))
                except json.JSONDecodeError:
                    continue
                if "error" in msg:
                    return False, msg["error"]
                status = msg.get("status", "")
                total, completed = msg.get("total"), msg.get("completed")
                if total and completed is not None:
                    pct = int(completed / total * 100)
                    if progress_cb:
                        progress_cb(pct, f"{status} {pct}%")
                elif progress_cb:
                    progress_cb(-1, status)
                if status == "success":
                    if progress_cb:
                        progress_cb(100, "完成")
                    return True, "完成"
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"
    return False, "拉取中断"


def ensure_model(name: str = LOCAL_MODEL, progress_cb=None) -> tuple[bool, str]:
    """一键就绪：服务→模型。失败原因直接可展示给用户。"""
    if not is_installed():
        return False, f"未安装 Ollama，请先安装：{INSTALL_URL}"
    if not ensure_started():
        return False, "Ollama 服务未能启动，请从开始菜单启动 Ollama 后重试"
    if has_model(name):
        return True, "模型已就绪"
    return pull_model(name, progress_cb)


def status_text() -> str:
    """供 UI 显示的一行状态。"""
    if not is_installed():
        return "未安装 Ollama（点击按钮查看安装指引）"
    if not is_running():
        return "Ollama 已安装，服务未运行"
    models = list_models()
    have = [m for m in (LOCAL_MODEL, LOCAL_MODEL_SMALL) if has_model(m)]
    return f"Ollama {version() or ''} 运行中" + (f"，模型：{', '.join(have)}" if have else "，尚未下载模型")


# ---------- llama-cpp-python（GGUF 直读，可选后端）----------
def llama_cpp_available() -> bool:
    """能否 import llama_cpp（未装返回 False，不报错）。"""
    try:
        import llama_cpp  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


def gguf_model_exists() -> bool:
    """LOCAL_MODEL_PATH 指向的 GGUF 文件是否存在。"""
    from core.config import LOCAL_MODEL_PATH
    return bool(LOCAL_MODEL_PATH) and Path(LOCAL_MODEL_PATH).is_file()


def local_ai_status() -> dict:
    """本地 AI 环境综合状态（供 UI/诊断）。"""
    return {
        "ollama_installed": is_installed(),
        "ollama_running": is_running(),
        "ollama_models": list_models(),
        "llama_cpp_installed": llama_cpp_available(),
        "gguf_path": LOCAL_MODEL_PATH if gguf_model_exists() else "",
        "enabled": os.environ.get("LOCAL_AI_ENABLED", "false").lower() == "true",
    }
