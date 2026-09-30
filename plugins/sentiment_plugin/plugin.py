# -*- coding: utf-8 -*-
"""示例插件：扩展情感分析能力。"""
from plugin_system import PluginBase


class Plugin(PluginBase):
    metadata = {
        "name": "sentiment_plugin",
        "version": "0.1.0",
        "author": "疏影雅集",
        "description": "扩展情感分析能力：对新闻/公告文本打分并输出情绪标签。",
        "permissions": ["data_access"],
    }

    _POS = ("利好", "增长", "盈利", "突破", "中标", "上调", "回购", "增持", "新高",
            "超预期", "大涨", "涨停", "扭亏")
    _NEG = ("利空", "亏损", "下跌", "大跌", "违约", "诉讼", "下调", "减持", "风险",
            "处罚", "低于预期", "造假", "爆雷", "跌停", "违规")

    def __init__(self):
        self._ctx = None

    def on_load(self, ctx):
        self._ctx = ctx

    def register_tools(self, ctx):
        ctx.register_tool(
            "plugin_sentiment_score",
            self.score,
            desc="对文本进行情感打分，返回 -1.0 ~ 1.0 与情绪标签。",
            schema={"text": "str"},
        )

    def score(self, text: str = "") -> dict:
        t = text or ""
        pos = sum(1 for w in self._POS if w in t)
        neg = sum(1 for w in self._NEG if w in t)
        total = pos + neg
        val = (pos - neg) / total if total else 0.0
        label = "利好" if val > 0.2 else ("利空" if val < -0.2 else "中性")
        return {"score": round(val, 3), "label": label,
                "pos_hits": pos, "neg_hits": neg}
