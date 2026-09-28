# -*- coding: utf-8 -*-
"""轻量国际化（i18n）：字典映射式中英文切换。

避免引入 Qt Linguist 复杂流程；机制完整、零第三方依赖：

    from i18n import tr, set_language, current_lang, LANGUAGES

    tr("app.title")            # 按当前语言返回文本（zh / en）
    set_language("en")         # 切换并持久化到 QSettings，立即生效

说明：本模块提供翻译机制与关键界面文本（窗口标题、免责声明、Web
界面入口、状态栏等）。全部界面文本迁移为增量工作——键缺失时自动
回退中文，保证任何语言下程序都不会出现空文本。
"""
from __future__ import annotations

import os

_LANG_KEY = "ui_language"
_DEFAULT_LANG = "zh"

# ---- 翻译表（zh 为基准；en 缺失时回退 zh） ----
_TRANSLATIONS: dict[str, dict[str, str]] = {
    "app.title": {
        "zh": "疏影 · 知微",
        "en": "Shuying · Insight",
    },
    "app.logo": {
        "zh": "🌙 疏影·知微",
        "en": "🌙 Shuying·Insight",
    },
    "disclaimer.title": {
        "zh": "免责声明与合规定位",
        "en": "Disclaimer & Compliance",
    },
    "disclaimer.body": {
        "zh": (
            "【免责声明】\n\n"
            "本工具为开源金融数据分析软件，仅供研究学习使用。\n\n"
            "不提供任何证券投资分析、预测或建议，不构成投资建议，不是荐股软件。\n\n"
            "开发者不具备证券投资咨询业务资格。\n\n"
            "投资有风险，入市需谨慎。\n\n"
            "（点击右上角关闭；完整声明可在『帮助→关于』查看）"
        ),
        "en": (
            "【Disclaimer】\n\n"
            "This tool is open-source financial data analysis software for research "
            "and study only.\n\n"
            "It does NOT provide securities investment analysis, forecasts or advice; "
            "it is not a stock-recommendation application.\n\n"
            "The developer holds no securities investment advisory license.\n\n"
            "Investing carries risk; be cautious.\n\n"
            "(Close via the top-right corner; full statement is under Help → About)"
        ),
    },
    "web.btn": {
        "zh": "🌐 打开 Web 界面",
        "en": "🌐 Open Web UI",
    },
    "web.started": {
        "zh": "Web 界面已启动：http://127.0.0.1:{port}",
        "en": "Web UI started: http://127.0.0.1:{port}",
    },
    "web.need_dep": {
        "zh": "Web 界面需要 fastapi/uvicorn。\n\n请手动执行：\npip install fastapi uvicorn[standard]",
        "en": "Web UI requires fastapi/uvicorn.\n\nPlease run:\npip install fastapi uvicorn[standard]",
    },
    "status.datasource_ok": {
        "zh": "数据源正常",
        "en": "Data sources OK",
    },
    "status.datasource_degraded": {
        "zh": "网络连接失败，已切换到缓存数据",
        "en": "Network failed, switched to cached data",
    },
    "status.lang_switched": {
        "zh": "语言已切换，部分界面将于重启后完全生效",
        "en": "Language switched; some UI texts fully apply after restart",
    },
    "lang.btn": {
        "zh": "EN",
        "en": "中",
    },
    "lang.tip": {
        "zh": "切换界面语言（当前：中文）",
        "en": "Switch UI language (current: English)",
    },
    "log.auto_learning": {
        "zh": "[自动学习] {msg}",
        "en": "[Auto-learning] {msg}",
    },
    "help.about": {
        "zh": "疏影·知微 使用帮助",
        "en": "Shuying·Insight User Guide",
    },
}

# 支持的语言（展示名）
LANGUAGES = {"zh": "中文", "en": "English"}


def current_lang() -> str:
    """返回当前语言（zh / en）。优先级：环境变量 > QSettings > 默认。"""
    env = os.environ.get("STOCKAI_LANG", "").strip().lower()
    if env in _TRANSLATIONS.get("app.title", {}):
        return env
    try:
        from PyQt6.QtCore import QSettings

        v = QSettings("Shuying", "ShuyingInsight").value(_LANG_KEY, _DEFAULT_LANG)
        v = str(v).strip().lower()
        if v in ("zh", "en"):
            return v
    except Exception:  # noqa: BLE001 - 无 Qt 环境（如纯 CLI 测试）时静默
        pass
    return _DEFAULT_LANG


def set_language(lang: str) -> str:
    """切换语言并持久化（QSettings）。返回实际生效的语言。"""
    lang = str(lang).strip().lower()
    if lang not in ("zh", "en"):
        lang = _DEFAULT_LANG
    try:
        from PyQt6.QtCore import QSettings

        QSettings("Shuying", "ShuyingInsight").setValue(_LANG_KEY, lang)
    except Exception:  # noqa: BLE001
        pass
    return lang


def tr(key: str, **kwargs) -> str:
    """按当前语言取文本；支持 {name} 占位符；键缺失回退中文/键名。"""
    lang = current_lang()
    entry = _TRANSLATIONS.get(key, {})
    text = entry.get(lang) or entry.get("zh") or key
    if kwargs:
        try:
            text = text.format(**kwargs)
        except (KeyError, ValueError):  # noqa: BLE001 - 占位符不匹配时原样返回
            pass
    return text


def t(key: str, lang: str = "zh") -> str:
    """显式指定语言取文本（不含占位符替换）。"""
    entry = _TRANSLATIONS.get(key, {})
    return entry.get(lang) or entry.get("zh") or key


def keys() -> list[str]:
    return sorted(_TRANSLATIONS)
