# -*- coding: utf-8 -*-
"""教学材料 → SFT 问答对（本地教师自蒸馏）。

流程：纯文本语料 → 分块 → 本地 Qwen2.5-7B 教师生成 Q&A → 去重 → 质检
      → distill.record_sft(source="curriculum")，零改动接入现有导出链。

教师用本地模型（raw=True 拿原始字符串，自行解析+落库），完全离线、零费用。
mock/失败/低质不进库（沿用蒸馏纪律）。
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Callable

from core.training import distill, resources

log = logging.getLogger("stockai.curriculum")

CHUNK_SIZE = 1800        # 中文字符/块（约 600-900 token，兼顾质量与速度）
CHUNK_OVERLAP = 200
MAX_PAIRS_PER_CHUNK = 5
MIN_ANSWER_CHARS = 40
MAX_COPY_RATIO = 0.6     # 答案 4-gram 出现在原文的比例上限，超过视为照搬

TEACHER_SYSTEM = (
    "你是金融教研专家。基于给定教材片段，生成面向投资分析的问答对，"
    "覆盖技术分析/基本面/宏观/风险/情绪等主题。问答要准确、可操作、不得照搬原文。"
    "只输出一个 JSON 对象，格式：{\"qa\": [{\"instruction\": \"问题\", \"output\": \"答案\"}]}，"
    "不要输出解释或代码块。"
)

_INSTR_MARK = ("?", "？", "如何", "什么是", "为什么", "解释", "分析", "计算",
               "说明", "列举", "比较", "判断", "预测", "评估", "怎样", "哪些")


def chunk_text(text: str, size: int = CHUNK_SIZE,
               overlap: int = CHUNK_OVERLAP) -> list[str]:
    """按句号/换行优先边界切块，带 overlap。"""
    text = re.sub(r"\s+\n", "\n", text).strip()
    if not text:
        return []
    chunks: list[str] = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + size, n)
        if end < n:
            # 优先在句末/换行处切
            for sep in ("。", "！", "？", ".\n", "\n\n", "\n", ". ", " "):
                cut = text.rfind(sep, start, end)
                if cut > start + size // 2:
                    end = cut + len(sep)
                    break
        chunks.append(text[start:end].strip())
        if end >= n:
            break
        start = end - overlap if end - overlap > start else end
    return [c for c in chunks if c]


def _parse_qa_list(content: str) -> list[dict]:
    """从教师原始输出解析 Q&A 列表，兼容 dict 包裹/裸数组/fence。"""
    text = content.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
    data = None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}|\[.*\]", text, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    if data is None:
        return []
    if isinstance(data, dict):
        for k in ("qa", "pairs", "items", "data", "questions", "list"):
            v = data.get(k)
            if isinstance(v, list):
                data = v
                break
        else:
            return []
    if not isinstance(data, list):
        return []
    out: list[dict] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        instr = item.get("instruction") or item.get("question") or item.get("prompt") or ""
        ans = item.get("output") or item.get("answer") or item.get("response") or ""
        if instr and ans:
            out.append({"instruction": str(instr).strip(), "output": str(ans).strip()})
    return out


def _ngrams(s: str, n: int = 4) -> set[str]:
    s = re.sub(r"\s+", "", s)
    return {s[i:i + n] for i in range(len(s) - n + 1)} if len(s) >= n else {s}


def _copy_ratio(answer: str, chunk: str) -> float:
    """答案 4-gram 出现在原文的比例（衡量是否照搬）。"""
    a = _ngrams(answer)
    if not a:
        return 0.0
    c = _ngrams(chunk)
    return len(a & c) / len(a)


def _quality_filter(pairs: list[dict], chunk: str) -> list[dict]:
    out: list[dict] = []
    for p in pairs:
        instr, ans = p["instruction"], p["output"]
        if len(ans) < MIN_ANSWER_CHARS:
            continue
        if "```" in ans or ans.strip().startswith(("[", "{")):
            continue
        if not (instr.endswith(("?", "？")) or any(m in instr for m in _INSTR_MARK)):
            continue
        if _copy_ratio(ans, chunk) > MAX_COPY_RATIO:
            continue
        out.append(p)
    return out


def _dedup(pairs: list[dict]) -> list[dict]:
    import hashlib
    seen: set[str] = set()
    out: list[dict] = []
    for p in pairs:
        key = hashlib.sha1(
            (re.sub(r"\s+", "", p["instruction"]) + "|"
             + re.sub(r"\s+", "", p["output"])).encode("utf-8")).hexdigest()
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def generate_qa_pairs(chunk: str, runner, max_pairs: int = MAX_PAIRS_PER_CHUNK
                      ) -> list[dict]:
    """调本地教师生成 Q&A。runner: LLMRunner（建议 backend=local）。"""
    user = (f"[教材片段]\n{chunk}\n\n"
            f"请生成至多 {max_pairs} 个高质量问答对。")
    try:
        content = runner.chat_json(node="curriculum", system=TEACHER_SYSTEM,
                                   user=user, raw=True, retries=1)
    except Exception as e:  # noqa: BLE001
        log.debug("教师生成失败：%s", e)
        return []
    if not isinstance(content, str) or not content.strip():
        return []
    pairs = _parse_qa_list(content)
    pairs = _quality_filter(pairs, chunk)
    return pairs[:max_pairs]


def distill_corpus(corpus_dir: Path | None = None, runner=None,
                    progress_cb: Callable[[int, str], None] | None = None
                    ) -> dict:
    """遍历语料库 → 蒸馏 Q&A → 落 sft.jsonl(source=curriculum)。

    runner: LLMRunner（建议 backend=local/mock=False）。若为 None 则尝试构造。
    返回 {files, chunks, pairs, written, skipped}。
    """
    if corpus_dir is None:
        corpus_dir = resources.CORPUS_DIR
    files = resources.corpus_files(corpus_dir)
    if not files:
        if progress_cb:
            progress_cb(-1, "语料库为空，请先获取教学资源")
        return {"files": 0, "chunks": 0, "pairs": 0, "written": 0, "skipped": 0}

    if runner is None:
        from core.llm import LLMRunner
        runner = LLMRunner(backend="local")

    total_pairs = 0
    written = 0
    skipped = 0
    n_chunks = 0
    for fi, f in enumerate(files):
        src = resources.get(f.stem)
        meta_base = {
            "source_id": f.stem,
            "license": src.license if src else "",
            "topic": ",".join(src.topics) if src else "",
        }
        text = f.read_text(encoding="utf-8")
        chunks = chunk_text(text)
        for ci, chunk in enumerate(chunks):
            n_chunks += 1
            pairs = _dedup(generate_qa_pairs(chunk, runner))
            if not pairs:
                skipped += 1
                continue
            for p in pairs:
                try:
                    distill.record_sft(
                        node="curriculum", system="", user=p["instruction"],
                        response=p["output"], model=runner.local_model,
                        source="curriculum", meta=meta_base)
                    written += 1
                    total_pairs += 1
                except Exception:  # noqa: BLE001
                    pass
            if progress_cb:
                pct = int((fi + (ci + 1) / len(chunks)) / len(files) * 100)
                progress_cb(pct, f"{f.stem} 块{ci + 1}/{len(chunks)} 已生成 {total_pairs} 对")
        if progress_cb:
            progress_cb(int((fi + 1) / len(files) * 100),
                        f"{f.stem} 完成，累计 {total_pairs} 对")
    if progress_cb:
        progress_cb(100, f"蒸馏完成：{total_pairs} 对（跳过 {skipped} 块）")
    return {"files": len(files), "chunks": n_chunks,
            "pairs": total_pairs, "written": written, "skipped": skipped}
