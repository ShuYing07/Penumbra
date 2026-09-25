# -*- coding: utf-8 -*-
"""直接用 requests 流式下载 Qwen2.5-3B-Instruct 全部文件到本地目录。

绕过 huggingface_hub 的 HEAD 元数据校验（hf-mirror.com 不满足校验）。
下载到 D:\\StockAIPredictor\\models\\Qwen2.5-3B-Instruct，YAML 改指向该路径。
"""
import os
import sys
from pathlib import Path

import requests

MIRROR = "https://hf-mirror.com"
MODEL_ID = "Qwen/Qwen2.5-3B-Instruct"
DEST = Path(r"D:\StockAIPredictor\models\Qwen2.5-3B-Instruct")

FILES = [
    "config.json",
    "generation_config.json",
    "merges.txt",
    "model-00001-of-00002.safetensors",
    "model-00002-of-00002.safetensors",
    "model.safetensors.index.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "vocab.json",
]


def download_file(fname: str) -> bool:
    url = f"{MIRROR}/{MODEL_ID}/resolve/main/{fname}"
    dest = DEST / fname
    if dest.exists() and dest.stat().st_size > 0:
        print(f"  [skip] {fname} 已存在 ({dest.stat().st_size / 1e6:.1f} MB)")
        return True
    print(f"  [get] {fname} ...")
    try:
        r = requests.get(url, stream=True, timeout=30, allow_redirects=True)
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        dl = 0
        tmp = dest.with_suffix(dest.suffix + ".tmp")
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                f.write(chunk)
                dl += len(chunk)
                if total > 0:
                    pct = dl * 100 // total
                    print(f"\r  {fname}: {dl/1e6:.1f}/{total/1e6:.1f} MB ({pct}%)", end="", flush=True)
        tmp.rename(dest)
        print(f"\n  [ok]  {fname} ({dest.stat().st_size / 1e6:.1f} MB)")
        return True
    except Exception as e:
        print(f"\n  [ERR] {fname}: {e}")
        if dest.with_suffix(dest.suffix + ".tmp").exists():
            dest.with_suffix(dest.suffix + ".tmp").unlink()
        return False


if __name__ == "__main__":
    DEST.mkdir(parents=True, exist_ok=True)
    print(f"下载 {MODEL_ID} → {DEST}")
    ok = True
    for f in FILES:
        if not download_file(f):
            ok = False
    if ok:
        print(f"\n全部完成 → {DEST}")
        print(f"YAML model_name_or_path 改为: {DEST.as_posix()}")
    else:
        print("\n部分文件下载失败，请重跑")
        sys.exit(1)
