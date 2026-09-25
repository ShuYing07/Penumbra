# -*- coding: utf-8 -*-
"""预下载 Qwen2.5-3B-Instruct 到 HF 缓存，走 hf-mirror.com 镜像。

LLaMA-Factory 0.9.5 + huggingface_hub 0.36.2 直传 HF_ENDPOINT 会导致
FileMetadataError（镜像 HEAD 响应头不满足 hub 校验）。
本脚本先用 snapshot_download 强制下载到本地缓存，
之后训练走 cached_file 即可离线加载。
"""
import os
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

from huggingface_hub import snapshot_download

MODEL_ID = "Qwen/Qwen2.5-3B-Instruct"

if __name__ == "__main__":
    print(f"开始下载 {MODEL_ID} from {os.environ['HF_ENDPOINT']} ...")
    path = snapshot_download(
        MODEL_ID,
        allow_patterns=[
            "config.json",
            "tokenizer.json",
            "tokenizer_config.json",
            "vocab.json",
            "merges.txt",
            "special_tokens_map.json",
            "generation_config.json",
            "model-*.safetensors",
            "model.safetensors.index.json",
        ],
        resume_download=True,
    )
    print(f"下载完成 → {path}")
