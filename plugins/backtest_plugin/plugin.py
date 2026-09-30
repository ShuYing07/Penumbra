# -*- coding: utf-8 -*-
"""示例插件：扩展回测策略（确定性规则，机械层）。"""
from plugin_system import PluginBase


class Plugin(PluginBase):
    metadata = {
        "name": "backtest_plugin",
        "version": "0.1.0",
        "author": "疏影雅集",
        "description": "扩展回测策略：均线双线策略与动量策略的确定性规则。",
        "permissions": ["data_access"],
    }

    def on_load(self, ctx):
        pass

    def register_tools(self, ctx):
        ctx.register_tool(
            "plugin_ma_cross_signal",
            self.ma_cross,
            desc="双均线交叉信号：快线上穿慢线返回 1（买入），下穿返回 -1（卖出）。",
            schema={"fast": "int", "slow": "int", "closes": "list"},
        )
        ctx.register_tool(
            "plugin_momentum_signal",
            self.momentum,
            desc="N 日动量信号：过去 N 日收益率为正则 1，负则 -1。",
            schema={"n": "int", "closes": "list"},
        )

    @staticmethod
    def _ma(series, n):
        if len(series) < n:
            return None
        return sum(series[-n:]) / n

    def ma_cross(self, fast: int = 5, slow: int = 20, closes: list | None = None) -> dict:
        c = closes or []
        fast_ma = self._ma(c, fast)
        slow_ma = self._ma(c, slow)
        if fast_ma is None or slow_ma is None:
            return {"signal": 0, "detail": "数据不足"}
        sig = 1 if fast_ma > slow_ma else (-1 if fast_ma < slow_ma else 0)
        return {"signal": sig, "fast_ma": round(fast_ma, 3), "slow_ma": round(slow_ma, 3)}

    def momentum(self, n: int = 5, closes: list | None = None) -> dict:
        c = closes or []
        if len(c) < n + 1 or c[-n - 1] == 0:
            return {"signal": 0, "detail": "数据不足"}
        ret = (c[-1] - c[-n - 1]) / c[-n - 1]
        return {"signal": 1 if ret > 0 else (-1 if ret < 0 else 0),
                "return_pct": round(ret * 100, 3)}
