# -*- coding: utf-8 -*-
"""自然语言意图解析：规则优先 + LLM兜底。"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class Intent:
    action: str
    ticker: str
    market: str = "CN"


# ---------- 规则版（快、零成本） ----------
def _parse_rules(text: str) -> Intent | None:
    t = text.strip()
    if not t:
        return None

    action = "analyze"
    if any(k in t for k in ["K线", "走势", "图表", "看图", "日线", "周线"]):
        action = "chart"
    elif any(k in t for k in ["新闻", "消息", "公告", "研报"]):
        action = "news"
    elif any(k in t for k in ["辩论", "多空"]):
        action = "debate"
    elif any(k in t for k in ["回测", "策略"]):
        action = "backtest"

    market = "CN"
    if any(k in t for k in ["美股", "纳斯达克", "纽交所", "NASDAQ", "NYSE"]):
        market = "US"
    elif any(k in t for k in ["港股", "恒生", "HK"]):
        market = "HK"

    m = re.search(r"(\d{6})", t)
    if m:
        return Intent(action, m.group(1), market)

    m = re.search(r"\b([A-Z]{1,5})\b", t)
    if m:
        return Intent(action, m.group(1), "US")

    cleaned = re.sub(
        r"(帮我|一下|看看|查看|分析|查询|研究|最新|今天|最近|有什么|的|什么|吗|呢|啊|吧)",
        "", t)
    m = re.search(r"[\u4e00-\u9fff]{2,4}", cleaned)
    if m:
        return Intent(action, m.group(0), market)
    return None


# ---------- LLM兜底（规则失败时） ----------
def parse_ticker_llm(text: str) -> Intent | None:
    """用LLM解析（需要已配置API Key）。"""
    try:
        from core.llm import LLMRunner
        runner = LLMRunner(mock=False)
        prompt = (
            "把用户输入解析为JSON，字段：action(analyze/chart/news/debate/backtest)、"
            "ticker(股票代码或名称)、market(CN/US/HK)。\n"
            f"用户输入：{text}\n只输出JSON。"
        )
        result = runner.chat_json("technical", "你是股票代码解析器。", prompt)
        if isinstance(result, dict) and result.get("ticker"):
            return Intent(
                action=result.get("action", "analyze"),
                ticker=result["ticker"],
                market=result.get("market", "CN"),
            )
    except Exception:
        pass
    return None


# ---------- 统一入口 ----------
def parse_intent(text: str) -> Intent | None:
    """规则优先，LLM兜底。"""
    result = _parse_rules(text)
    if result and result.ticker:
        return result
    return parse_ticker_llm(text)


if __name__ == "__main__":
    tests = [
        "帮我分析一下贵州茅台",
        "看看600519的K线",
        "腾讯最近有什么新闻",
        "AAPL多空辩论",
        "看看宁德时代走势",
    ]
    for q in tests:
        print(f"{q} -> {parse_intent(q)}")
