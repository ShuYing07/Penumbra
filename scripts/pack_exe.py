# -*- coding: utf-8 -*-
"""一键打包脚本：spec 构建 → 拷贝使用说明/.env → 体积报告。

用法：venv\\Scripts\\python.exe scripts\\pack_exe.py [--console]
  默认打 windowed 终版；--console 打控制台调试版。
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENV_PY = ROOT / "venv" / "Scripts" / "python.exe"
DIST = ROOT / "dist" / "StockAIPredictor"


def dir_size_mb(p: Path) -> float:
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) / 1024 / 1024


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--console", action="store_true", help="打控制台调试版（默认 windowed 终版）")
    args = ap.parse_args()

    os.environ["STOCKAI_PACK_CONSOLE"] = "1" if args.console else "0"
    for d in (ROOT / "build", ROOT / "dist"):
        if d.exists():
            print(f"清理 {d.name}/")
            shutil.rmtree(d, ignore_errors=True)

    print("== PyInstaller 构建（约几分钟）==")
    r = subprocess.run(
        [str(VENV_PY), "-m", "PyInstaller", str(ROOT / "packaging" / "stockai.spec"),
         "--noconfirm", "--distpath", str(ROOT / "dist"), "--workpath", str(ROOT / "build")],
        cwd=str(ROOT))
    if r.returncode != 0:
        print("构建失败")
        return 1
    if not (DIST / "StockAIPredictor.exe").exists():
        print("未找到产物 exe")
        return 1

    # 交付物：使用说明 + .env（有真 key 直接带上的本机包；分发他人前请先替换）
    shutil.copy2(ROOT / "packaging" / "使用说明.txt", DIST / "使用说明.txt")
    src_env = ROOT / ".env"
    dst_env = DIST / ".env"
    if src_env.exists() and not dst_env.exists():
        shutil.copy2(src_env, dst_env)
        print("已复制 .env（含本机 key；如分发给他人请先删除/替换）")

    print(f"\n完成：{DIST}")
    print(f"体积：{dir_size_mb(DIST):.1f} MB")
    print("自检命令：StockAIPredictor.exe --selftest（结果见 data/selftest.log）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
