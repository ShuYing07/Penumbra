# -*- coding: utf-8 -*-
"""模型加载器：统一处理开发环境和打包环境的模型路径。"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def get_model_path(model_name: str = "kronos-small") -> str | None:
    """按优先级返回模型路径，找不到返回None。"""
    # 1. 环境变量
    env_path = os.environ.get("KRONOS_MODEL_PATH")
    if env_path and os.path.exists(env_path):
        return env_path

    # 2. 程序目录下 models/ 文件夹
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.abspath(__file__))

    candidates = [
        Path(base) / "models" / model_name,
        Path(base) / "data" / "training" / model_name,
    ]
    for p in candidates:
        if p.exists():
            return str(p)

    # 3. PyInstaller内置
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        p = Path(sys._MEIPASS) / "models" / model_name
        if p.exists():
            return str(p)

    return None


def check_model_available(model_name: str = "kronos-small") -> bool:
    """检查模型是否可用。"""
    return get_model_path(model_name) is not None


if __name__ == "__main__":
    p = get_model_path()
    print(f"模型路径: {p}")
    print(f"可用: {check_model_available()}")
