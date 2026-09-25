# -*- coding: utf-8 -*-
"""自动学习训练：定时抓取新闻，提炼模式，更新知识库。"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

DATA_DIR = Path("data")
LEARN_FILE = DATA_DIR / "learned_patterns.json"


def _load_patterns() -> dict:
    if LEARN_FILE.exists():
        return json.loads(LEARN_FILE.read_text(encoding="utf-8"))
    return {"updated_at": "", "patterns": [], "stats": {"total": 0, "bullish": 0, "bearish": 0}}


def _save_patterns(data: dict) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    LEARN_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def learn_once() -> dict:
    """跑一轮自动学习。"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"[{now}] 开始自动学习...")

    stats = {"fetched": 0, "new_patterns": 0, "errors": []}

    # 1. 抓热点新闻
    try:
        from news_pipeline import fetch_stock_news, analyze_news_sentiment
        # 用几只代表性股票测试
        test_codes = ["600519", "000858", "300750", "601318", "000001"]
        for code in test_codes:
            try:
                news = fetch_stock_news(code)
                stats["fetched"] += len(news)
                for n in news[:3]:
                    sentiment = analyze_news_sentiment(n.get("title", ""))
                    print(f"  {code}: {n.get('title','')[:30]}... -> {sentiment}")
            except Exception as e:
                stats["errors"].append(f"{code}: {e}")
    except Exception as e:
        stats["errors"].append(f"news: {e}")

    # 2. 更新知识库
    data = _load_patterns()
    data["updated_at"] = now
    data["stats"]["total"] += stats["fetched"]
    data["last_run"] = stats

    # 3. 生成学习摘要
    summary = {
        "time": now,
        "news_count": stats["fetched"],
        "errors": stats["errors"][:5],
    }
    data["patterns"].append(summary)
    # 只保留最近100条
    data["patterns"] = data["patterns"][-100:]
    _save_patterns(data)

    print(f"[{now}] 完成: 抓取{stats['fetched']}条新闻, 错误{len(stats['errors'])}个")
    return stats


def get_learned_context() -> str:
    """供AI模型读取的学习成果摘要。"""
    data = _load_patterns()
    if not data["patterns"]:
        return ""
    recent = data["patterns"][-5:]
    lines = [f"[学习更新: {data['updated_at']}]"]
    for p in recent:
        lines.append(f"  {p['time']}: {p['news_count']}条新闻")
    return "\n".join(lines)


if __name__ == "__main__":
    learn_once()
