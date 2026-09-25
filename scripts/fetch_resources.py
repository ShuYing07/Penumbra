# -*- coding: utf-8 -*-
"""批量获取+解析教学资源→ data/training/corpus_raw/*.txt。

用法：
  venv\\Scripts\\python.exe scripts\\fetch_resources.py                 # 取全部内置源
  venv\\Scripts\\python.exe scripts\\fetch_resources.py --sources id1,id2
  venv\\Scripts\\python.exe scripts\\fetch_resources.py --list          # 仅列出源
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.config import ensure_utf8_stdio, setup_logging
from core.training import resources


def main() -> int:
    ensure_utf8_stdio()
    setup_logging()
    ap = argparse.ArgumentParser(description="获取教学资源到本地语料库")
    ap.add_argument("--sources", help="逗号分隔的资源 id，缺省取全部")
    ap.add_argument("--list", action="store_true", help="仅列出内置源后退出")
    args = ap.parse_args()

    srcs = resources.list_sources()
    if args.list:
        print(f"内置源 {len(srcs)} 个：")
        for s in srcs:
            print(f"  [{s.id}] {s.name}  ({s.kind}/{s.language}/{s.license})  {s.topics}")
        return 0

    ids = [s.id for s in srcs] if not args.sources else args.sources.split(",")
    print(f"待获取 {len(ids)} 个源 → {resources.CORPUS_DIR}")
    ok_n = 0
    for sid in ids:
        print(f"\n--- {sid} ---")
        ok, msg, _ = resources.fetch_and_parse(sid)
        print(("OK  " if ok else "FAIL") + " " + msg)
        if ok:
            ok_n += 1
    print(f"\n完成：{ok_n}/{len(ids)} 成功")
    print("语料统计：", resources.corpus_stats())
    return 0 if ok_n == len(ids) else 1


if __name__ == "__main__":
    raise SystemExit(main())
