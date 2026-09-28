# -*- coding: utf-8 -*-
"""国际化基础（模块八）：轻量字典式中英文切换。

设计（避免 Qt Linguist 重流程，适合桌面工具）：
- I18N['key'] : 取当前语言文案；缺省回退中文；
- set_language('zh'|'en') : 全局切换（QSettings 持久化）；
- 支持占位符格式化：I18N('welcome', name='张三')。
"""
from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger("stockai.i18n")

# 文案字典（核心界面 + 合规声明 + 通用按钮）
_STRINGS = {
    "zh": {
        "app_title": "疏影·知微",
        "tagline": "本地优先的开源 AI 金融数据分析终端",
        "nav_chat": "对话分析",
        "nav_market": "市场概览",
        "nav_watchlist": "自选股",
        "nav_chart": "K线图",
        "nav_backtest": "策略回测",
        "nav_debate": "多空辩论",
        "nav_portfolio": "组合回测",
        "nav_optimize": "参数寻优",
        "nav_replay": "信号回放",
        "nav_learning": "学习库",
        "nav_decisions": "决策记录",
        "nav_logs": "分析日志",
        "nav_audit": "合规审计",
        "nav_graph": "产业图谱",
        "nav_stocks": "股票大全",
        "nav_history": "历史分析",
        "nav_collab": "协作空间",
        "nav_risk": "风控",
        "btn_search": "搜索",
        "btn_analyze": "开始分析",
        "btn_add_watch": "添加自选",
        "btn_refresh": "刷新",
        "btn_retry": "重试",
        "btn_open_account": "前往官方开户页面",
        "status_loading": "正在获取数据...",
        "status_no_data": "请输入股票代码（如 600519 / AAPL / 0700.HK）",
        "compliance_footer": "⚠️ 本工具仅供研究学习，不构成投资建议，不是荐股软件。",
        "disclaimer_title": "免责声明",
        "disclaimer_body": ("本工具为开源金融数据分析软件，仅供研究学习使用。"
                            "不提供任何证券投资分析、预测或建议，不构成任何投资建议。"
                            "投资有风险，入市需谨慎。"),
        "welcome_1": "欢迎使用！本工具帮你快速了解行情、指标与新闻（纯数据展示）。",
        "welcome_2": "输入股票代码（如 600519 / AAPL）即可查看 K 线与分析。",
        "welcome_3": "所有分析仅供研究学习，不构成投资建议。",
        "api_hint": "粘贴任意 OpenAI 兼容接口的 Key（DeepSeek/通义千问/智谱等）",
    },
    "en": {
        "app_title": "Shuying Insight",
        "tagline": "Local-first open-source AI financial data terminal",
        "nav_chat": "Chat",
        "nav_market": "Market",
        "nav_watchlist": "Watchlist",
        "nav_chart": "Charts",
        "nav_backtest": "Backtest",
        "nav_debate": "Bull vs Bear",
        "nav_portfolio": "Portfolio",
        "nav_optimize": "Optimize",
        "nav_replay": "Replay",
        "nav_learning": "Learning",
        "nav_decisions": "Decisions",
        "nav_logs": "Logs",
        "nav_audit": "Audit",
        "nav_graph": "Industry Map",
        "nav_stocks": "Stock Universe",
        "nav_history": "History",
        "nav_collab": "Workspace",
        "nav_risk": "Risk",
        "btn_search": "Search",
        "btn_analyze": "Analyze",
        "btn_add_watch": "Add",
        "btn_refresh": "Refresh",
        "btn_retry": "Retry",
        "btn_open_account": "Open Broker Page",
        "status_loading": "Loading data...",
        "status_no_data": "Enter a ticker (e.g. 600519 / AAPL / 0700.HK)",
        "compliance_footer": "⚠️ For research only. Not investment advice.",
        "disclaimer_title": "Disclaimer",
        "disclaimer_body": ("Open-source financial data tool for research only. "
                            "Not investment advice. Trade at your own risk."),
        "welcome_1": "Welcome! Explore market data, indicators and news.",
        "welcome_2": "Type a ticker (600519 / AAPL) to view charts.",
        "welcome_3": "For research only. Not investment advice.",
        "api_hint": "Paste any OpenAI-compatible API key (DeepSeek/Qwen/Zhipu...)",
    },
}

_LANG = "zh"


def set_language(lang: str) -> None:
    """切换语言（zh/en）；非法值回退 zh。"""
    global _LANG
    _LANG = lang if lang in _STRINGS else "zh"
    try:
        from PyQt6.QtCore import QSettings
        QSettings("StockAI", "StockAIPredictor").setValue("ui_lang", _LANG)
    except Exception:  # noqa: BLE001
        pass


def current_language() -> str:
    return _LANG


def t(key: str, **fmt) -> str:
    """取文案（支持 {name} 占位符）。"""
    text = _STRINGS.get(_LANG, _STRINGS["zh"]).get(
        key, _STRINGS["zh"].get(key, key))
    if fmt:
        try:
            text = text.format(**fmt)
        except Exception:  # noqa: BLE001
            pass
    return text


def t_zh(key: str) -> str:
    return _STRINGS["zh"].get(key, key)


def t_en(key: str) -> str:
    return _STRINGS["en"].get(key, key)


def available_languages() -> list[str]:
    return list(_STRINGS.keys())
