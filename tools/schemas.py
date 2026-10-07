# -*- coding: utf-8 -*-
"""工具输入 Schema（Pydantic v2）。

每个模型对应一个工具的入参：``Field(description=...)`` 会原样进入
JSON Schema，也就是 LLM 看到的"参数说明书"。描述写得好不好，直接决定
模型会不会在正确的时机、用正确的参数调用工具——docstring 不是装饰，是 API。

写作原则（调研 MCP 最佳实践后的落地）：
- 参数名用业务语义（code 而非 id）；
- 必填项越少越好，能默认就默认；
- 用 ge/le 把取值范围写进 Schema，让模型不必猜边界。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class FetchStockIn(BaseModel):
    """获取一只股票的行情数据与最新技术指标快照。"""
    code: str = Field(description="股票代码：600519 / SH600519 / AAPL / 0700.HK")


class IndicatorsIn(BaseModel):
    """计算指定技术指标的最新值（客观数值，不含任何判断）。"""
    code: str = Field(description="股票代码")
    indicators: List[str] = Field(
        default=["rsi14", "macd", "sma20", "sma60", "boll"],
        description="指标名列表，可选：sma5/sma10/sma20/sma60/boll/rsi14/macd")


class NewsIn(BaseModel):
    """检索与某只股票相关的新闻资讯。"""
    code: str = Field(description="股票代码")
    limit: int = Field(default=8, ge=1, le=30, description="最多返回条数")


class BacktestIn(BaseModel):
    """对一只股票运行指定策略的历史回测（历史统计，不代表未来）。"""
    code: str = Field(description="股票代码")
    strategy: str = Field(
        default="ma_cross",
        description="策略名：ma_cross(双均线)/rsi_reversion(RSI回归)/"
                    "macd_cross(MACD金叉死叉)/buy_hold(买入持有)")
    params: dict = Field(default_factory=dict, description="策略参数（可空）")


class SearchStocksIn(BaseModel):
    """按代码/名称/拼音检索股票。"""
    query: str = Field(description="查询词：代码、名称或拼音缩写，如 gzmt / 茅台")
    market: Optional[str] = Field(default=None, description="市场过滤：A股/港股/美股/指数")
    limit: int = Field(default=10, ge=1, le=50, description="最多返回条数")


class MarketOverviewIn(BaseModel):
    """获取今日市场概览（指数、北向资金、两市成交额）。"""


class RealtimeIn(BaseModel):
    """获取股票实时快照（现价/涨跌/成交额）。"""
    code: str = Field(description="股票代码")


class DrawingsIn(BaseModel):
    """读取用户在某股票图上画的标注（趋势线/水平线/斐波那契/矩形）。"""
    code: str = Field(description="股票代码")


class ScreenerIn(BaseModel):
    """按结构化条件筛选股票（客观筛选，不做推荐排序）。"""
    market: Optional[str] = Field(default=None, description="市场：A股/港股/美股/指数")
    board: Optional[str] = Field(default=None, description="板块/行业关键词")
    price_min: Optional[float] = Field(default=None, description="价格下限")
    price_max: Optional[float] = Field(default=None, description="价格上限")
    chg_min: Optional[float] = Field(default=None, description="涨跌幅下限(%)")
    chg_max: Optional[float] = Field(default=None, description="涨跌幅上限(%)")
    limit: int = Field(default=20, ge=1, le=100, description="最多返回条数")


class ChartControlIn(BaseModel):
    """图表 AI 控制面指令：增删指标/绘图、切换周期、重置。

    仅做图表展示控制，不产出任何荐股/目标价/收益承诺（合规）。
    """
    ticker: str = Field(default="", description="标的代码（如 SH600519），留空作用于当前图")
    action: str = Field(description=(
        "指令：add_indicator / remove_indicator / add_drawing / remove_last_drawing "
        "/ set_timeframe / set_ticker / reset"))
    id: Optional[str] = Field(default=None, description="指标 id（add/remove_indicator 用）")
    tool: Optional[str] = Field(default=None, description="绘图工具 id（add_drawing 用）")
    tf: Optional[str] = Field(default=None, description="周期：1m/5m/15m/30m/1h/1d/1w/1mo")
    params: Optional[Dict[str, Any]] = Field(default=None, description="指标参数字典")
    points: Optional[List[Dict[str, Any]]] = Field(default=None, description="绘图点列表[{x,y}]")
    meta: Optional[Dict[str, Any]] = Field(default=None, description="绘图附加元数据")


class ChartReadIn(BaseModel):
    """读取当前图表视窗内可见的 K 线数据（AI 控制面"读数据"能力）。"""
    ticker: str = Field(default="", description="标的代码，留空用当前图")
    limit: int = Field(default=120, ge=1, le=1000, description="返回最近 N 根 K 线")


class ChartScreenshotIn(BaseModel):
    """导出当前图表状态快照（结构化，非位图；供 Agent 理解"图上看什么"）。"""
    ticker: str = Field(default="", description="标的代码，留空用当前图")


__all__ = [
    "FetchStockIn", "IndicatorsIn", "NewsIn", "BacktestIn", "SearchStocksIn",
    "MarketOverviewIn", "RealtimeIn", "DrawingsIn", "ScreenerIn",
    "ChartControlIn", "ChartReadIn", "ChartScreenshotIn",
]
