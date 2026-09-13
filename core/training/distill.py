# -*- coding: utf-8 -*-
"""蒸馏数据积累（完全离线可积累，训练时再导出）。

两条数据轨：
1. SFT 教师演示（sft.jsonl）：云端 DeepSeek 每次成功推理的完整 (system,user → response)，
   是高质量结构化输出示范；本地学生模型的输出也记 source=student，供对比/蒸馏。
2. 决策偏好标注（preferences.jsonl）：决策满 10 交易日反思后，按"方向是否正确"
   打 good/bad 标签 + 实际收益，未来用教师对 bad 样本重新生成即可配成 DPO 对。

纪律：
- 记录失败永不阻塞主流程（调用方 try 包住）；
- 全部本地落盘（data/distill/），不外传；
- mock 桩输出不进语料（垃圾进垃圾出）。
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

from core.config import DATA_DIR, now_cn

log = logging.getLogger("stockai.distill")

DISTILL_DIR = DATA_DIR / "distill"
SFT_FILE = DISTILL_DIR / "sft.jsonl"
PREF_FILE = DISTILL_DIR / "preferences.jsonl"
_lock = threading.Lock()

# 单条语料上限（user prompt 可能含几十条新闻，避免文件无限膨胀）
_MAX_CHARS = 12000


def _append(path: Path, row: dict) -> None:
    DISTILL_DIR.mkdir(parents=True, exist_ok=True)
    line = json.dumps(row, ensure_ascii=False)
    with _lock:
        with path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")


def _clip(text: str) -> str:
    text = text or ""
    return text if len(text) <= _MAX_CHARS else text[:_MAX_CHARS] + "\n…[截断]"


def record_sft(*, node: str, system: str, user: str, response: str, model: str,
               source: str, meta: dict | None = None) -> None:
    """记录一次真实模型推理。source: teacher(云端) / student(本地) / curriculum(教学蒸馏)。"""
    try:
        _append(SFT_FILE, {
            "ts": now_cn().isoformat(timespec="seconds"),
            "node": node, "model": model, "source": source,
            "ticker": (meta or {}).get("ticker", ""),
            "system": _clip(system), "user": _clip(user),
            "response": _clip(response),
        })
    except Exception as e:  # noqa: BLE001
        log.debug("SFT 语料记录失败：%s", e)


def record_preference(*, decision_id: int, ticker: str, action: str,
                      trader_output: str, instruction: str,
                      realized_return_pct: float, aligned: bool | None) -> None:
    """决策到期后记录偏好标签。aligned=True/False/None(观望类无方向)。"""
    try:
        _append(PREF_FILE, {
            "ts": now_cn().isoformat(timespec="seconds"),
            "decision_id": decision_id, "ticker": ticker, "action": action,
            "realized_return_pct": realized_return_pct,
            "label": ("good" if aligned else "bad") if aligned is not None else "neutral",
            "instruction": _clip(instruction),
            "output": _clip(trader_output or ""),
        })
    except Exception as e:  # noqa: BLE001
        log.debug("偏好语料记录失败：%s", e)


def _count(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("rb") as f:
        return sum(1 for _ in f)


def stats() -> dict:
    """语料库统计：条数 + 按 source/label 分布。"""
    sft_by_source: dict[str, int] = {}
    pref_by_label: dict[str, int] = {}
    if SFT_FILE.exists():
        for line in SFT_FILE.read_text(encoding="utf-8").splitlines():
            try:
                k = json.loads(line).get("source", "?")
                sft_by_source[k] = sft_by_source.get(k, 0) + 1
            except json.JSONDecodeError:
                continue
    if PREF_FILE.exists():
        for line in PREF_FILE.read_text(encoding="utf-8").splitlines():
            try:
                k = json.loads(line).get("label", "?")
                pref_by_label[k] = pref_by_label.get(k, 0) + 1
            except json.JSONDecodeError:
                continue
    return {"sft_total": _count(SFT_FILE), "sft_by_source": sft_by_source,
            "pref_total": _count(PREF_FILE), "pref_by_label": pref_by_label}


def export_llamafactory(out_dir: str | Path | None = None,
                         sources: tuple[str, ...] | None = None) -> dict:
    """导出为 LLaMA-Factory 可直接训练的数据集（alpaca SFT + 偏好标注）。

    sources=None 导出全部 SFT 语料（sft_llamafactory.json）；
    sources=('curriculum',) 只导出教学蒸馏语料（curriculum_sft.json），
    可与 teacher/student 混合训练防遗忘。
    返回生成文件清单。训练需独立 GPU 环境（本程序不内置 torch），
    仓库 https://github.com/hiyouga/LLaMA-Factory 配 dataset_info 后：
      - sft_llamafactory.json → llamafactory-cli train（qwen2.5-7b LoRA，≥12GB 显存建议）
      - preference_llamafactory.json → 先让教师对 bad 样本重生成 chosen，再 DPO。
    """
    out = Path(out_dir) if out_dir else (DISTILL_DIR / "export")
    out.mkdir(parents=True, exist_ok=True)

    sft_rows = []
    if SFT_FILE.exists():
        for line in SFT_FILE.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if sources is not None and r.get("source", "") not in sources:
                continue
            sft_rows.append({
                "instruction": (r.get("system", "") + "\n\n" + r.get("user", "")).strip(),
                "input": "", "output": r.get("response", ""),
            })
    sft_name = ("sft_llamafactory.json" if sources is None
                else f"{'_'.join(sources)}_sft.json")
    sft_path = out / sft_name
    sft_path.write_text(json.dumps(sft_rows, ensure_ascii=False, indent=1), encoding="utf-8")

    pref_rows = []
    if PREF_FILE.exists():
        for line in PREF_FILE.read_text(encoding="utf-8").splitlines():
            try:
                pref_rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    pref_path = out / "preference_llamafactory.json"
    pref_path.write_text(json.dumps(pref_rows, ensure_ascii=False, indent=1), encoding="utf-8")

    readme = out / "README_训练说明.txt"
    readme.write_text(
        "蒸馏数据集导出（StockAIPredictor）\n"
        "================================\n\n"
        "1) sft_llamafactory.json：SFT 监督微调集（alpaca 格式：instruction/output）。\n"
        "   建议只用 output 为合法 JSON 的行；dataset_info.json 已自动生成，直接训练：\n"
        "   llamafactory-cli train training_configs/qwen2_5_qlora_curriculum.yaml\n\n"
        "2) preference_llamafactory.json：决策偏好标注（label=good/bad + 实际涨跌%）。\n"
        "   DPO 需要同一 prompt 的 chosen/rejected 成对：\n"
        "   - good 行直接作 chosen；bad 行用充值后的 DeepSeek 重新推理生成 chosen，\n"
        "     原输出作 rejected，即得完整 DPO 对（后续版本提供自动配对脚本）。\n\n"
        "3) 训练完成后把合并权重用 ollama create 导入，在 .env 设\n"
"   STOCKAI_LOCAL_MODEL=你的模型标签，即可替换默认学生模型。\n\n"
"4) 教学资源蒸馏语料 source=curriculum：导出参数 sources=('curriculum',)\n"
"   生成 curriculum_sft.json；dataset_info.json 中已注册 stockai_curriculum，\n"
"   训练 YAML 的 dataset: stockai_curriculum 即可直接加载。\n",
        encoding="utf-8")

    # dataset_info.json：LLaMA-Factory 必需的数据集注册文件，放在 --dataset_dir 下
    dataset_info = {
        "stockai_curriculum": {
            "file_name": "curriculum_sft.json",
            "columns": {"prompt": "instruction", "query": "input", "response": "output"},
        },
        "stockai_sft": {
            "file_name": "sft_llamafactory.json",
            "columns": {"prompt": "instruction", "query": "input", "response": "output"},
        },
    }
    (out / "dataset_info.json").write_text(
        json.dumps(dataset_info, ensure_ascii=False, indent=2), encoding="utf-8")

    return {"sft": str(sft_path), "sft_name": sft_name, "sft_rows": len(sft_rows),
            "preference": str(pref_path), "preference_rows": len(pref_rows),
            "readme": str(readme), "dataset_info": str(out / "dataset_info.json")}
