# -*- coding: utf-8 -*-
"""把蒸馏语料导出为 LLaMA-Factory 训练集（SFT + 偏好标注）。

用法：
  venv\\Scripts\\python.exe scripts\\export_distill.py                       # 导出全部
  venv\\Scripts\\python.exe scripts\\export_distill.py --sources curriculum # 仅教研语料
输出：data\\distill\\export\\（含训练说明 README_训练说明.txt）
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.config import ensure_utf8_stdio, setup_logging
from core.training import distill


def main() -> int:
    ensure_utf8_stdio()
    setup_logging()
    ap = argparse.ArgumentParser(description="导出蒸馏语料为 LLaMA-Factory 训练集")
    ap.add_argument("--sources", help="逗号分隔的 source 过滤（如 curriculum）；缺省导出全部")
    args = ap.parse_args()

    print("当前语料：", distill.stats())
    sources = tuple(args.sources.split(",")) if args.sources else None
    r = distill.export_llamafactory(sources=sources)
    print("导出完成：")
    for k, v in r.items():
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
