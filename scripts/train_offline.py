# -*- coding: utf-8 -*-
"""离线训练全流程编排 CLI（教学资源蒸馏 → 导出 → 训练 → 合并 → 导入）。

用法（主 venv）：
  venv\\Scripts\\python.exe scripts\\train_offline.py distill   # 本地教师蒸馏语料
  venv\\Scripts\\python.exe scripts\\train_offline.py export    # 导出 curriculum 训练集
  venv\\Scripts\\python.exe scripts\\train_offline.py train      # QLoRA 训练（需 venv_train）
  venv\\Scripts\\python.exe scripts\\train_offline.py merge      # 合并 LoRA
  venv\\Scripts\\python.exe scripts\\train_offline.py import     # 导入 Ollama + 切模型
  venv\\Scripts\\python.exe scripts\\train_offline.py all        # 全流程
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.config import ensure_utf8_stdio, setup_logging
from core.training import curriculum, distill, ollama_import, resources

YAML_TRAIN = Path("training_configs/qwen2_5_qlora_curriculum.yaml")
YAML_MERGE = Path("training_configs/merge_lora.yaml")
MODELFILE = Path("training_configs/Modelfile.stockai")
MODEL_NAME = "stockai-qwen-curriculum"


def cmd_distill() -> int:
    if not resources.corpus_files():
        print("语料库为空，先跑：venv\\Scripts\\python.exe scripts\\fetch_resources.py")
        return 1
    from core.llm import LLMRunner
    runner = LLMRunner(backend="local")
    r = curriculum.distill_corpus(runner=runner, progress_cb=lambda p, m: print(f"[{p}%] {m}"))
    print("蒸馏结果：", r)
    print("语料统计：", distill.stats())
    return 0


def cmd_export() -> int:
    r = distill.export_llamafactory(sources=("curriculum",))
    print("导出完成：", r)
    return 0


def _need_venv():
    venv = ollama_import.find_venv_train()
    if not venv:
        print("未找到 venv_train，先跑：powershell -File scripts\\bootstrap_venv_train.ps1")
        return None
    print(f"venv_train: {venv}")
    return venv


def cmd_train() -> int:
    venv = _need_venv()
    if not venv:
        return 1
    ok, msg = ollama_import.stop_local_model()
    print(msg)
    yaml = (ollama_import.PROJECT_ROOT / YAML_TRAIN).resolve()
    rc = ollama_import.run_training(yaml, venv, on_line=lambda s: print(s))
    print(f"训练退出码：{rc}")
    return 0 if rc == 0 else 1


def cmd_merge() -> int:
    venv = _need_venv()
    if not venv:
        return 1
    yaml = (ollama_import.PROJECT_ROOT / YAML_MERGE).resolve()
    ok, msg, _ = ollama_import.merge_lora(yaml, venv, on_line=lambda s: print(s))
    print(msg)
    return 0 if ok else 1


def cmd_import() -> int:
    mf = (ollama_import.PROJECT_ROOT / MODELFILE).resolve()
    ok, msg = ollama_import.ollama_create(MODEL_NAME, mf, on_line=lambda s: print(s))
    print(msg)
    if not ok:
        return 1
    ollama_import.set_local_model(MODEL_NAME, persist=True)
    print(f"已设为本地学生模型：{MODEL_NAME}（.env STOCKAI_LOCAL_MODEL）")
    return 0


def main() -> int:
    ensure_utf8_stdio()
    setup_logging()
    ap = argparse.ArgumentParser(description="离线训练全流程编排")
    ap.add_argument("stage", choices=["distill", "export", "train", "merge", "import", "all"])
    args = ap.parse_args()
    if args.stage == "all":
        for stage in (cmd_distill, cmd_export, cmd_train, cmd_merge, cmd_import):
            print(f"\n=== {stage.__name__} ===")
            if stage() != 0:
                print(f"阶段 {stage.__name__} 失败，中止")
                return 1
        return 0
    return {
        "distill": cmd_distill, "export": cmd_export, "train": cmd_train,
        "merge": cmd_merge, "import": cmd_import,
    }[args.stage]()


if __name__ == "__main__":
    raise SystemExit(main())
