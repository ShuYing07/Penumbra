# -*- coding: utf-8 -*-
"""领域微调（可选）· LoRA 示例脚本（模块三）。

参考 finance-specialist-v7 的 LoRA 配置：r=8, alpha=16, attention-only。
本脚本是【占位/模板】：不自动下载模型、不自动训练。
用途：在用户环境装好依赖后，将训练数据放入 scripts/lora_finetune/data/ 即可运行。

依赖（需手动安装，红线：本脚本不自行安装）：
    pip install peft transformers datasets accelerate

用法：
    python scripts/lora_finetune/finetune_example.py --base-model Qwen/Qwen2.5-7B-Instruct \
        --data-dir scripts/lora_finetune/data --output-dir scripts/lora_finetune/output
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_DATA = _HERE / "data"

# 训练数据格式：JSON Lines，每行 {"instruction","input","output"}
# 覆盖三类金融任务：财报QA对 / 研报摘要 / 新闻情感标注


def build_dataset(data_dir: Path):
    import json

    rows = []
    for fp in sorted(data_dir.glob("*.jsonl")):
        with fp.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
    return rows


def train(args: argparse.Namespace) -> None:
    try:
        import torch
        from peft import LoraConfig, get_peft_model, TaskType
        from transformers import AutoModelForCausalLM, AutoTokenizer, TrainingArguments
        from trl import SFTTrainer
    except ImportError as e:
        print(f"[finetune] 缺少依赖：{e}")
        print("请手动执行：pip install peft transformers datasets accelerate trl")
        sys.exit(2)

    rows = build_dataset(Path(args.data_dir))
    if not rows:
        print(f"[finetune] {args.data_dir} 下无 *.jsonl 训练数据，跳过训练。")
        sys.exit(0)

    # LoRA 配置（attention-only，r=8, alpha=16）
    lora = LoraConfig(
        task_type=TaskType.CAUSAL_LM,
        r=8,
        lora_alpha=16,
        lora_dropout=0.05,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],  # attention-only
    )
    model = AutoModelForCausalLM.from_pretrained(
        args.base_model, torch_dtype=torch.bfloat16 if torch.cuda.is_available() else torch.float32)
    tokenizer = AutoTokenizer.from_pretrained(args.base_model)
    model = get_peft_model(model, lora)
    print(f"[finetune] 可训练参数：{sum(p.numel() for p in model.parameters() if p.requires_grad) / 1e6:.2f}M")

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    train_args = TrainingArguments(
        output_dir=str(out), per_device_train_batch_size=1,
        num_train_epochs=3, logging_steps=10, save_strategy="epoch",
        report_to="none")
    trainer = SFTTrainer(
        model=model, tokenizer=tokenizer, args=train_args,
        train_dataset=rows, dataset_text_field="output", max_seq_length=2048)
    trainer.train()
    trainer.save_model(str(out))
    print(f"[finetune] LoRA 权重已保存到 {out}")
    print("合并/导出：model.merge_and_unload() 后 push 或转 GGUF 供 Ollama 使用。")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="疏影·知微 金融 LoRA 微调示例")
    ap.add_argument("--base-model", default="Qwen/Qwen2.5-7B-Instruct")
    ap.add_argument("--data-dir", default=str(_DATA))
    ap.add_argument("--output-dir", default=str(_HERE / "output"))
    train(ap.parse_args())
