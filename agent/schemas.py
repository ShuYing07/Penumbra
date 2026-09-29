# -*- coding: utf-8 -*-
"""Agent 工具调用层的 Pydantic 结构化 Schema。

参考 open-finance-pydanticAI / iFinD MCP 的做法：每个工具用带描述的参数
Schema 约束输入类型，用统一 ToolResult 约束返回格式，从根上减少
"乱调工具 / 解析返回失败"两类问题。

pydantic v2（随 fastapi 安装），BaseModel + Field(description=...) 的
描述同时用于：① LLM 理解工具语义；② MCP Server 暴露 JSON Schema。
"""
from __future__ import annotations

from typing import Any, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# 工具输入 Schema
# ---------------------------------------------------------------------------
class FetchStockIn(BaseModel):
    """获取一只股票的行情数据与最新技术指标快照。"""
    code: str = Field(description="股票代码：600519 / SH600519 / AAPL / 0700.HK")


class IndicatorsIn(BaseModel):
    """计算指定技术指标的最新值。"""
    code: str = Field(description="股票代码")
    indicators: List[str] = Field(
        default=["rsi14", "macd", "sma20", "sma60", "boll"],
        description="指标名列表，可选：sma5/sma10/sma20/sma60/boll/rsi14/macd")


class NewsIn(BaseModel):
    """检索与某只股票相关的新闻资讯。"""
    code: str = Field(description="股票代码")
    limit: int = Field(default=8, ge=1, le=30, description="最多返回条数")


class BacktestIn(BaseModel):
    """对一只股票运行指定策略的历史回测。"""
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
    pass


class RealtimeIn(BaseModel):
    """获取股票实时快照（现价/涨跌/成交额）。"""
    code: str = Field(description="股票代码")


class DrawingsIn(BaseModel):
    """读取用户在某股票图上画的标注（趋势线/水平线/斐波那契/矩形）。"""
    code: str = Field(description="股票代码")


class ScreenerIn(BaseModel):
    """按结构化条件筛选股票。"""
    market: Optional[str] = Field(default=None, description="市场：A股/港股/美股/指数")
    board: Optional[str] = Field(default=None, description="板块/行业关键词")
    price_min: Optional[float] = Field(default=None, description="价格下限")
    price_max: Optional[float] = Field(default=None, description="价格上限")
    chg_min: Optional[float] = Field(default=None, description="涨跌幅下限(%)")
    chg_max: Optional[float] = Field(default=None, description="涨跌幅上限(%)")
    limit: int = Field(default=20, ge=1, le=100, description="最多返回条数")


# ---------------------------------------------------------------------------
# 统一输出
# ---------------------------------------------------------------------------
class ToolResult(BaseModel):
    """所有工具的统一返回：ok 标识 + 数据 + 说明。"""
    ok: bool = Field(description="调用是否成功")
    tool: str = Field(description="工具名")
    data: Any = Field(default=None, description="结构化结果（JSON 兼容）")
    note: str = Field(default="", description="数据来源/口径说明")


def ok_result(tool: str, data: Any, note: str = "") -> ToolResult:
    return ToolResult(ok=True, tool=tool, data=data, note=note)


def fail_result(tool: str, error: str) -> ToolResult:
    return ToolResult(ok=False, tool=tool, data=None, note=f"调用失败：{error}")
