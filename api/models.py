# -*- coding: utf-8 -*-
"""REST API —— Pydantic 请求/响应模型（企业版模块三）。

注意：fastapi/pydantic 为可选依赖。桌面版无需安装；启动 API 服务前请先
手动安装：pip install fastapi uvicorn[standard]
"""
from __future__ import annotations

from typing import Optional

try:
    from pydantic import BaseModel, Field
except Exception:  # noqa: BLE001  (无 pydantic 时仅定义占位)
    BaseModel = object  # type: ignore

    class Field:  # type: ignore
        def __init__(self, *a, **k):
            pass


# ---- 认证 ----
class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    role: str
    tenant_id: str


# ---- 分析 ----
class AnalysisRequest(BaseModel):
    stock_code: str = Field(..., description="股票代码，如 SH600519 / AAPL")
    engine: str = "auto"        # auto / deepseek / mock


class AnalysisResponse(BaseModel):
    stock_code: str
    summary: Optional[str] = None
    status: str = "ok"


# ---- 回测 ----
class BacktestRequest(BaseModel):
    stock_code: str
    strategy: str = "ma_cross"
    params: dict = {}
    start_date: Optional[str] = None
    end_date: Optional[str] = None


class BacktestResult(BaseModel):
    stock_code: str
    strategy: str
    total_return: float = 0.0
    max_drawdown: float = 0.0
    sharpe: float = 0.0
    winrate: float = 0.0


# ---- 组合 ----
class PositionItem(BaseModel):
    stock_code: str
    shares: int = 0
    cost: float = 0.0


class PortfolioResponse(BaseModel):
    positions: list[PositionItem] = []
    market_value: float = 0.0
    cash: float = 0.0


# ---- 审计 ----
class AuditLogEntry(BaseModel):
    id: int
    ts: str
    user_id: str
    action: str
    resource: str = ""
    detail: str = ""
