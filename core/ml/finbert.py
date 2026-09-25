# -*- coding: utf-8 -*-
"""中文金融新闻情感分析（FinBERT-zh，本地离线，零 token）。

模型：yiyanghkust/finbert-zh（基于 BERT，三分类 正面/中性/负面）。
设计：
- 懒加载单例：首次调用才下载（~400MB，走 hf-mirror 国内镜像），之后常驻内存；
- 输出情感分 score∈[-1, +1]（-1最负，+1最正）+ 类别，喂给情绪节点作确定性因子；
- 任何失败（模型未下好/推理异常）优雅降级返回 None，绝不拖垮主流程；
- CPU 推理，单条毫秒级。
"""
from __future__ import annotations

import logging
import os

log = logging.getLogger("stockai.ml.finbert")

_MODEL = None
_TOK = None
_READY: bool | None = None  # None=未尝试, True/False=结果


def _load() -> bool:
    global _MODEL, _TOK, _READY
    if _READY is not None:
        return _READY
    try:
        os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
        from transformers import AutoModelForSequenceClassification, AutoTokenizer
        name = "yiyanghkust/finbert-tone-chinese"
        _TOK = AutoTokenizer.from_pretrained(name)
        _MODEL = AutoModelForSequenceClassification.from_pretrained(name)
        _MODEL.eval()
        _READY = True
        log.info("FinBERT-zh 加载完成")
    except Exception as e:  # noqa: BLE001
        log.warning("FinBERT 加载失败（将降级）：%s", str(e)[:160])
        _READY = False
    return _READY


def _label_map() -> dict:
    try:
        id2 = _MODEL.config.id2label
        return {str(v).lower(): k for k, v in id2.items()}
    except Exception:  # noqa: BLE001
        return {}


def sentiment_one(text: str) -> dict:
    """对单段中文文本打情感分。返回 {label, score(-1~1), pos,neu,neg}。"""
    if not text or not str(text).strip():
        return {"label": "中性", "score": 0.0, "note": "空文本"}
    if not _load():
        return {"label": "不可用", "score": 0.0, "note": "FinBERT未加载"}
    try:
        import torch
        inputs = _TOK(text[:512], return_tensors="pt", truncation=True,
                      padding=True, max_length=256)
        with torch.no_grad():
            logits = _MODEL(**inputs).logits
        probs = torch.softmax(logits, dim=-1)[0].tolist()
        labels = [str(_MODEL.config.id2label.get(i, str(i))).lower()
                  for i in range(len(probs))]
        d = dict(zip(labels, probs))
        pos = float(d.get("positive", d.get("pos", 0.0)))
        neg = float(d.get("negative", d.get("neg", 0.0)))
        neu = float(d.get("neutral", d.get("neu", 0.0)))
        score = round(pos - neg, 3)
        if pos >= max(neg, neu):
            label = "正面"
        elif neg >= max(pos, neu):
            label = "负面"
        else:
            label = "中性"
        return {"label": label, "score": score,
                "pos": round(pos, 3), "neu": round(neu, 3), "neg": round(neg, 3)}
    except Exception as e:  # noqa: BLE001
        log.warning("FinBERT 推理失败：%s", str(e)[:160])
        return {"label": "错误", "score": 0.0, "note": str(e)[:100]}


def sentiment_batch(texts: list[str]) -> dict:
    """对一批标题打情感，返回汇总 {avg_score, pos/neu/neg 计数, detail}。"""
    if not texts:
        return {"avg_score": 0.0, "n": 0}
    scores, labels = [], {"正面": 0, "中性": 0, "负面": 0}
    for t in texts[:15]:
        r = sentiment_one(t)
        scores.append(r.get("score", 0.0))
        labels[r.get("label", "中性")] = labels.get(r.get("label", "中性"), 0) + 1
    avg = round(sum(scores) / len(scores), 3) if scores else 0.0
    if avg >= 0.1:
        mood = "偏多"
    elif avg <= -0.1:
        mood = "偏空"
    else:
        mood = "中性"
    return {"avg_score": avg, "mood": mood, "counts": labels,
            "n": len(scores), "note": f"FinBERT本地情感：{mood}（均分{avg}）"}
