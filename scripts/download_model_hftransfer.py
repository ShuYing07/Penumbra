# -*- coding: utf-8 -*-
"""用 hf_transfer 多连接并行下载 Qwen2.5-3B-Instruct 全部文件。

hf_transfer 是 Rust 实现的高速下载器，支持多分片并行。
绕过 huggingface_hub 的 HEAD 元数据校验问题。
下载到 D:\\StockAIPredictor\\models\\Qwen2.5-3B-Instruct。
"""
import os
import sys
from pathlib import Path

os.environ["TOKIO_WORKER_THREADS"] = "8"
import hf_transfer  # noqa: E402

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


class Progress:
    def __init__(self, fname, total):
        self.fname = fname
        self.total = total
        self.last = 0

    def __call__(self, downloaded):
        if downloaded - self.last >= 50 * 1024 * 1024 or (self.total and downloaded >= self.total):
            pct = downloaded * 100 // self.total if self.total else 0
            print(f"  {self.fname}: {downloaded/1e6:.1f}/{self.total/1e6:.1f} MB ({pct}%)", flush=True)
            self.last = downloaded


def download_file(fname: str) -> bool:
    dest = DEST / fname
    if dest.exists() and dest.stat().st_size > 0:
        print(f"  [skip] {fname} ({dest.stat().st_size/1e6:.1f} MB)")
        return True
    # 清理可能的 .tmp 残留
    tmp = DEST / (fname + ".tmp")
    if tmp.exists():
        tmp.unlink()
    url = f"{MIRROR}/{MODEL_ID}/resolve/main/{fname}"
    print(f"  [get] {fname}")
    try:
        # 先 HEAD 拿 content-length
        import requests
        r = requests.head(url, timeout=15, allow_redirects=True)
        total = int(r.headers.get("content-length", 0))
        cb = Progress(fname, total) if total else None
        hf_transfer.download(
            url,
            str(dest),
            max_files=8,
            chunk_size=10 * 1024 * 1024,  # 10MB chunks
            parallel_failures=2,
            max_retries=3,
            callback=cb,
        )
        sz = dest.stat().st_size
        print(f"  [ok]  {fname} ({sz/1e6:.1f} MB)")
        return True
    except Exception as e:
        print(f"  [ERR] {fname}: {e}")
        if dest.exists():
            dest.unlink()
        return False


if __name__ == "__main__":
    DEST.mkdir(parents=True, exist_ok=True)
    print(f"hf_transfer 下载 {MODEL_ID} → {DEST}")
    ok = True
    for f in FILES:
        if not download_file(f):
            ok = False
    if ok:
        print(f"\n全部完成 → {DEST}")
    else:
        print("\n部分失败，请重跑")
        sys.exit(1)
