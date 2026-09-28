# -*- coding: utf-8 -*-
"""疏影·知微 企业版 REST API（企业版模块三）。

启动（需先手动安装 fastapi + uvicorn）：
    venv\\Scripts\\python.exe -m api.main --host 127.0.0.1 --port 8000
    或  uvicorn api.main:app --reload

端点：
    POST /auth/login                登录（返回 JWT）
    GET  /analysis/{stock_code}     获取分析报告（需认证）
    POST /backtest                  提交回测任务（需认证）
    GET  /portfolio                 获取组合信息（需认证）
    GET  /audit-log                 获取审计日志（需 admin）
    GET  /health                    健康检查（无认证）
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from fastapi import FastAPI, Depends, HTTPException, Header
    from fastapi.responses import JSONResponse
except Exception as e:  # noqa: BLE001
    raise RuntimeError(
        "缺少可选依赖 fastapi。请先手动安装：pip install fastapi uvicorn[standard]"
    ) from e

from api.models import (LoginRequest, TokenResponse, AnalysisResponse,  # noqa: E402
                        BacktestRequest, BacktestResult, PortfolioResponse)
from api.dependencies import get_current_user  # noqa: E402
from core import auth_service, audit_logger  # noqa: E402

app = FastAPI(
    title="疏影·知微 API",
    version="0.7.0",
    description="本地优先的 AI 金融数据分析终端 —— 企业版 REST 接口。"
                "仅供研究学习，不构成任何投资建议。",
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "version": "0.7.0"}


@app.post("/auth/login", response_model=TokenResponse)
def login(body: LoginRequest) -> TokenResponse:
    user = auth_service.verify_password(body.username, body.password)
    if user is None:
        audit_logger.log_operation("unknown", "login_failed", body.username)
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    token = auth_service.create_token(user["user_id"], user["tenant_id"], user["role"])
    audit_logger.log_operation(user["user_id"], "login", f"user={body.username}")
    return TokenResponse(access_token=token, expires_in=auth_service.TOKEN_TTL,
                         role=user["role"], tenant_id=user["tenant_id"])


def _auth(authorization: str, role: str | None = None) -> dict:
    """认证包装：PermissionError → HTTPException(401)。"""
    try:
        return get_current_user(authorization, require_role=role)
    except PermissionError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e


@app.get("/analysis/{stock_code}", response_model=AnalysisResponse)
def analysis(stock_code: str,
             authorization: str = Header(default="")) -> AnalysisResponse:
    user = _auth(authorization, role="analyst")
    audit_logger.log_operation(user["sub"], "analysis", stock_code,
                               resource="analysis")
    # 数据分析走 core.data.service（纯数据统计，不输出投资建议）
    try:
        from core.data import service
        df, _status = service.get_daily(stock_code)
        rows = len(df)
        summary = f"{stock_code} 日线 {rows} 行（{_status}）"
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"数据获取失败: {e}")
    return AnalysisResponse(stock_code=stock_code, summary=summary)


@app.post("/backtest", response_model=BacktestResult)
def backtest(body: BacktestRequest,
             authorization: str = Header(default="")) -> BacktestResult:
    user = _auth(authorization, role="analyst")
    audit_logger.log_operation(user["sub"], "backtest",
                               f"{body.stock_code}/{body.strategy}")
    try:
        from core.data import service
        from core.quant.backtest import run_backtest  # 项目内已实现
        df, _ = service.get_daily(body.stock_code)
        res = run_backtest(df, strategy=body.strategy, params=body.params)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"回测失败: {e}")
    return BacktestResult(stock_code=body.stock_code, strategy=body.strategy,
                          total_return=float(res.get("total", 0)),
                          max_drawdown=float(res.get("maxdd", 0)),
                          sharpe=float(res.get("sharpe", 0)),
                          winrate=float(res.get("winrate", 0)))


@app.get("/portfolio", response_model=PortfolioResponse)
def portfolio(authorization: str = Header(default="")) -> PortfolioResponse:
    user = _auth(authorization, role="viewer")
    audit_logger.log_operation(user["sub"], "portfolio_view")
    return PortfolioResponse()


@app.get("/audit-log")
def audit_log(limit: int = 100,
              authorization: str = Header(default="")) -> list[dict]:
    user = _auth(authorization, role="admin")
    return audit_logger.query_audit(limit=limit)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
