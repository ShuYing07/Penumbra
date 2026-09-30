# -*- coding: utf-8 -*-
"""轻量金融新闻情感规则（零依赖，不触发 akshare 等重型导入）。

供 core.data.news_pipeline / news_pipeline / streaming.stream_engine 等复用，
保证后台线程/流处理链路不被重型 import 阻塞。
"""
from __future__ import annotations

_BULLISH = [
    "上涨", "增长", "盈利", "利好", "突破", "增持", "回购", "超预期", "受益",
    "中标", "签约", "投产", "获奖", "创新高", "分红", "回购", "改善", "回暖",
    "翻倍", "提速", "放量", "新高", "涨停",
]
_BEARISH = [
    "下跌", "亏损", "利空", "减持", "处罚", "违规", "立案", "下调", "退市",
    "跌停", "爆雷", "诉讼", "失败", "下滑", "违约", "风险", "承压", "恶化",
    "减值", "冻结", "调查", "st", "暂停", "退订",
]


def analyze_sentiment(text: str) -> str:
    """基于关键词的金融情感判断：利好 / 利空 / 中性。"""
    t = (text or "").lower()
    score = 0
    for w in _BULLISH:
        if w in t:
            score += 1
    for w in _BEARISH:
        if w in t:
            score -= 1
    if score > 0:
        return "利好"
    if score < 0:
        return "利空"
    return "中性"


def sentiment_score(text: str) -> int:
    """返回整数情感分（供排序/聚合）。"""
    t = (text or "").lower()
    score = 0
    for w in _BULLISH:
        if w in t:
            score += 1
    for w in _BEARISH:
        if w in t:
            score -= 1
    return score
