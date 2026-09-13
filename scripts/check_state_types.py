# -*- coding: utf-8 -*-
"""递归扫描 gather_facts 状态中的 numpy 类型，精确定位序列化隐患。"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["STOCKAI_MOCK"] = "1"

import numpy as np
from core.agents.graph import gather_facts


def scan(obj, path="root", depth=0):
    if depth > 6:
        return
    t = type(obj)
    mod = t.__module__ or ""
    if mod.startswith("numpy") or "numpy" in str(t):
        print(f"  NUMPY  {path} -> {t} value={obj!r}")
    elif isinstance(obj, dict):
        for k, v in obj.items():
            scan(v, f"{path}.{k}", depth + 1)
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj[:20]):
            scan(v, f"{path}[{i}]", depth + 1)


for ticker in ("SH600519",):
    print(f"=== {ticker} ===")
    st = gather_facts(ticker)
    scan(st)
    print("扫描完成")
