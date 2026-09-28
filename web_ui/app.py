# -*- coding: utf-8 -*-
"""Web UI（企业版·混合模式）：FastAPI + WebSocket 流式分析。

启动（需先手动安装依赖）：
    pip install fastapi uvicorn[standard]
    venv\\Scripts\\python.exe -m web_ui.app        # http://127.0.0.1:8200

端点：
    GET  /api/analysis/{code}   行情数据统计摘要（纯数据，不含建议）
    POST /api/backtest          历史回测（T+1 次日开盘成交）
    GET  /api/portfolio         组合信息（示例/占位）
    WS   /ws/analysis           流式输出分析进度事件
    GET  /                      静态页面（static/index.html）

合规：本服务仅做数据展示与历史统计，不提供任何投资建议。
"""
from __future__ import annotations

from typing import Optional

# 未安装 fastapi 时给出清晰提示
try:
    from fastapi import FastAPI, WebSocket, HTTPException
    from fastapi.responses import FileResponse
    from pydantic import BaseModel
    _HAS_FASTAPI = True
except ImportError:  # pragma: no cover - 未安装时的导入路径
    FastAPI = WebSocket = HTTPException = BaseModel = None  # type: ignore
    FileResponse = None  # type: ignore
    _HAS_FASTAPI = False

from core.data import service

PORT = 8200
STATIC_DIR = __import__("pathlib").Path(__file__).parent / "static"


if _HAS_FASTAPI:
    class BacktestRequest(BaseModel):  # type: ignore[valid-type, misc]
        ticker: str
        fast: int = 5
        slow: int = 20
        initial_capital: float = 100_000.0
else:
    BacktestRequest = None  # type: ignore[assignment,misc]


def create_app():
    if FastAPI is None:
        raise RuntimeError(
            "未安装 fastapi/uvicorn，请先手动执行："
            "pip install fastapi uvicorn[standard]")
    app = FastAPI(title="疏影·知微 Web UI", version="0.7.0")

    @app.get("/")
    def index():
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/health")
    def health():
        return {"status": "ok", "role": "data-tool"}

    @app.get("/api/analysis/{code}")
    def analysis(code: str):
        """行情数据统计摘要：K线统计/涨跌幅/近期表现（纯历史统计）。"""
        try:
            bars, status = service.get_daily(code)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=f"数据获取失败: {e}")
        if bars is None or len(bars) == 0:
            raise HTTPException(status_code=404, detail=f"无 {code} 的历史数据")
        close = bars["close"]
        stats = {
            "ticker": code, "source": status, "bars": len(bars),
            "last_close": float(close.iloc[-1]),
            "period_change_pct": round((close.iloc[-1] / close.iloc[0] - 1) * 100, 2)
            if len(close) > 1 and close.iloc[0] else None,
            "max": float(close.max()), "min": float(close.min()),
            "mean": round(float(close.mean()), 2),
            "date_start": str(bars.index.min().date()),
            "date_end": str(bars.index.max().date()),
        }
        return {"data": stats,
                "disclaimer": "本工具为开源金融数据分析软件，仅供研究学习，"
                              "不构成任何投资建议，不是荐股软件。"}

    @app.get("/api/bars/{code}")
    def bars(code: str, limit: int = 120):
        """K 线数据（倒序最近 limit 根，供前端画图）。"""
        try:
            df, _ = service.get_daily(code)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=f"数据获取失败: {e}")
        if df is None or len(df) == 0:
            raise HTTPException(status_code=404, detail=f"无 {code} 的历史数据")
        tail = df.tail(limit)
        out = [{"date": str(i.date()), "open": float(r["open"]),
                "high": float(r["high"]), "low": float(r["low"]),
                "close": float(r["close"]), "volume": float(r["volume"]) if "volume" in r else 0}
               for i, r in tail.iterrows()]
        return {"bars": out}

    @app.post("/api/backtest")
    def backtest(req: BacktestRequest):  # type: ignore[valid-type, misc]
        """历史回测：T+1 次日开盘成交，输出完整绩效指标。"""
        try:
            from core.backtester import run_backtest
            bars, _ = service.get_daily(req.ticker)
            result = run_backtest(bars, fast=req.fast, slow=req.slow,
                                  initial_capital=req.initial_capital)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=f"回测失败: {e}")
        return {"ticker": req.ticker, **result,
                "disclaimer": "本页面仅为历史数据统计与策略逻辑验证，"
                              "不构成投资建议，不代表未来收益。"}

    @app.get("/api/portfolio")
    def portfolio():
        return {"items": [], "note": "组合数据在桌面端本地管理（示例为空）"}

    @app.websocket("/ws/analysis")
    async def ws_analysis(ws: WebSocket):  # type: ignore[valid-type, misc]
        await ws.accept()
        await ws.send_json({"event": "progress", "stage": "connected",
                            "message": "Web UI 已连接（数据工具模式）"})
        await ws.close()

    return app


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(create_app(), host="127.0.0.1", port=PORT)
