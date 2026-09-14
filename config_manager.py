# -*- coding: utf-8 -*-
"""用户 API Key 本地管理（开源合规版）。

职责：
- 从项目根目录 .env 读取 API Key；
- .env 缺失或 Key 为空时，给出友好的首次配置提示（不抛出、不打印密钥）；
- 提供脱敏展示（仅显示首尾各几位），绝不把完整 Key 打到日志/界面/错误信息里。

注意：本模块只负责"读取与脱敏展示"，不收集、不上传、不存储任何 Key 到远端。
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENV_PATH = ROOT / ".env"
EXAMPLE_PATH = ROOT / ".env.example"


def _read_env_key(key: str) -> str:
    """从 .env 文件读取单个键值（不依赖已加载的 os.environ）。"""
    if not ENV_PATH.exists():
        return ""
    try:
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            if k.strip() == key:
                return v.strip().strip('"').strip("'")
    except Exception:  # noqa: BLE001
        return ""
    return os.environ.get(key, "").strip()


def get_deepseek_key() -> str:
    """返回用户配置的 DEEPSEEK_API_KEY（实际指向兼容端点的云端 Key）。"""
    return _read_env_key("DEEPSEEK_API_KEY") or os.environ.get("DEEPSEEK_API_KEY", "").strip()


def mask_key(key: str) -> str:
    """脱敏：只保留前4位+后4位，中间打码。绝不返回完整 Key。"""
    if not key:
        return "(未配置)"
    if len(key) <= 8:
        return "****"
    return f"{key[:4]}…{key[-4:]}"


def ensure_configured() -> tuple[bool, str]:
    """启动时检查 Key 是否已配置。返回 (ok, 提示文案)。"""
    if not ENV_PATH.exists():
        return False, (
            "请创建 .env 文件并填入您的 API Key。\n"
            "可复制 .env.example 为 .env，编辑其中的 DEEPSEEK_API_KEY 后重启程序。"
        )
    key = get_deepseek_key()
    if not key:
        return False, (
            "请创建 .env 文件并填入您的 API Key。\n"
            "当前 .env 中未配置 DEEPSEEK_API_KEY，请编辑 .env 填入后重启。"
        )
    return True, f"已加载 API Key：{mask_key(key)}"


def is_dev_mode() -> bool:
    """是否开启开发者模式（功能开关）。

    优先级：环境变量 DEV_MODE=true/false > 本地 config.yaml 的 dev.mode。
    默认关闭。开发者模式下显示调试面板、更新走 dev 频道。
    """
    env = os.environ.get("DEV_MODE", "").strip().lower()
    if env in ("1", "true", "yes", "on"):
        return True
    if env in ("0", "false", "no", "off"):
        return False
    # 读本地 config.yaml（可选，失败即默认关）
    yaml_cfg = ROOT / "config.yaml"
    if yaml_cfg.exists():
        try:
            for line in yaml_cfg.read_text(encoding="utf-8").splitlines():
                s = line.strip()
                if s.startswith("dev:"):
                    # 下一行 mode: true
                    continue
                if s.startswith("mode:"):
                    return "true" in s.lower()
        except Exception:  # noqa: BLE001
            pass
    return False


def update_channel() -> str:
    """更新通道：开发者模式用 dev，普通用户用 stable。"""
    return "dev" if is_dev_mode() else "stable"


# ---------- 版本与更新检查 ----------
APP_VERSION = "0.1.0"
REPO_API = "https://api.github.com/repos/ShuYing07/Penumbra/releases/latest"
REPO_URL = "https://github.com/ShuYing07/Penumbra"
RELEASES_URL = "https://github.com/ShuYing07/Penumbra/releases"


def check_update(timeout: float = 6.0) -> dict:
    """用标准库 urllib 查询 GitHub Release，对比版本。

    只查询、只弹窗提示，绝不自动下载/替换。返回:
      {current, latest, has_update, url, error}
    """
    import json
    import urllib.request

    out = {"current": APP_VERSION, "latest": APP_VERSION,
           "has_update": False, "url": RELEASES_URL, "error": None}
    try:
        req = urllib.request.Request(
            REPO_API, headers={"User-Agent": "StockAIPredictor"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
        out["latest"] = data.get("tag_name", APP_VERSION).lstrip("vV")
        out["url"] = data.get("html_url") or RELEASES_URL
        out["has_update"] = out["latest"] != APP_VERSION
    except Exception as e:  # noqa: BLE001
        # 无 Release / 网络不可达：不报错，直接引导用户去 Releases 页
        out["error"] = str(e)[:160]
    return out


if __name__ == "__main__":
    ok, msg = ensure_configured()
    print(msg)