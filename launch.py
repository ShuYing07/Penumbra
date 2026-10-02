# -*- coding: utf-8 -*-
"""零配置启动入口（模块七 · 参考九章·ALGOR launch.py「双击即用」）。

运行方式：
    双击 launch.py，或命令行：python launch.py

行为：
1. 环境自检：Python 版本、虚拟环境（venv）、核心依赖；
2. 缺失项 → 打印清晰的安装指引并以 exit code 2 退出
   （遵守「新依赖手动安装」红线，绝不自动 pip install）；
3. 环境就绪 → 启动「疏影·知微」主程序（app/main.py）。

可选依赖（缺失不影响启动，仅对应功能降级/提示）：
    akshare（实时行情/财报）、skfolio（组合优化）、
    websockets（实时行情引擎）、PyQt6-WebEngine（世界指数地图）。
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent
VENV_PY = APP_ROOT / "venv" / "Scripts" / "python.exe"
REQ_FILE = APP_ROOT / "requirements.txt"

# 核心依赖：缺失则无法启动
CORE_DEPS = ("PyQt6", "pandas", "numpy")
# 可选依赖：缺失则对应功能降级（不阻塞启动）
OPTIONAL_DEPS = ("akshare", "skfolio", "websockets", "PyQt6.QtWebEngineWidgets")

_MISSING_CORE: list[str] = []
_MISSING_OPT: list[str] = []


def _python_version_ok() -> bool:
    return sys.version_info >= (3, 10)


def _check_imports() -> None:
    for mod in CORE_DEPS:
        if importlib.util.find_spec(mod) is None:
            _MISSING_CORE.append(mod)
    for mod in OPTIONAL_DEPS:
        if importlib.util.find_spec(mod) is None:
            _MISSING_OPT.append(mod)


def _print_report() -> None:
    print("=" * 56)
    print("疏影·知微 启动自检")
    print("=" * 56)
    print(f"项目目录   : {APP_ROOT}")
    print(f"Python     : {sys.version.split()[0]} "
          f"{'✅ 版本满足 (>=3.10)' if _python_version_ok() else '❌ 版本过低 (需 >=3.10)'}")
    print(f"虚拟环境   : {'✅ 存在' if VENV_PY.exists() else '❌ 未创建 venv'}")
    print(f"核心依赖   : {', '.join(_MISSING_CORE) if _MISSING_CORE else '✅ 全部就绪'}")
    print(f"可选依赖   : {', '.join(_MISSING_OPT) if _MISSING_OPT else '✅ 全部就绪'}")


def _install_hint() -> int:
    """输出安装指引，退出码 2（提示用户手动安装，不自动执行）。"""
    print()
    print("❌ 环境未就绪，无法启动。请手动执行以下步骤：")
    if not VENV_PY.exists():
        print("  1) 创建虚拟环境：")
        print("     python -m venv venv")
        print("     venv\\Scripts\\activate")
    if _MISSING_CORE:
        print(f"  2) 安装核心依赖：")
        print(f"     {' '.join(_MISSING_CORE)} 缺失")
        print(f"     venv\\Scripts\\python.exe -m pip install -r {REQ_FILE}")
    if _MISSING_OPT:
        print(f"  3) （可选）安装增强依赖以启用对应功能：")
        print(f"     venv\\Scripts\\python.exe -m pip install "
              f"{' '.join(_MISSING_OPT)}")
    print()
    print("完成后重新运行 launch.py（或直接运行 venv\\Scripts\\python.exe app\\main.py）")
    return 2


def main() -> int:
    _check_imports()
    _print_report()
    if not _python_version_ok() or _MISSING_CORE or not VENV_PY.exists():
        return _install_hint()
    if _MISSING_OPT:
        print(f"⚠️ 可选依赖未安装（{', '.join(_MISSING_OPT)}），"
              f"相关功能将降级或提示，不影响主程序启动。")
    print()
    print("✅ 环境就绪，正在启动疏影·知微…")
    main_py = APP_ROOT / "app" / "main.py"
    if not main_py.exists():
        print(f"❌ 未找到主程序：{main_py}")
        return 1
    return subprocess.call([str(VENV_PY), "-B", str(main_py)])


if __name__ == "__main__":
    sys.exit(main())
