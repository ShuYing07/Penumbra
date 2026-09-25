# -*- coding: utf-8 -*-
"""MCP Server：stdio 协议 + HTTP 模式，带认证和限流。"""
from __future__ import annotations

import json
import time
from collections import defaultdict


# ---------- 简单限流 ----------
_rate: dict[str, list[float]] = defaultdict(list)


def check_rate_limit(key: str, max_per_min: int = 60) -> bool:
    now = time.time()
    arr = [t for t in _rate[key] if now - t < 60]
    if len(arr) >= max_per_min:
        return False
    arr.append(now)
    _rate[key] = arr
    return True


# ---------- 核心查询 ----------
def _handle_search(query: str, limit: int = 10) -> list[dict]:
    from core.search.stock_index import search_stocks, load_index
    idx = load_index()
    return search_stocks(query, idx, limit=limit)


def _handle_quote(ticker: str) -> dict:
    from core.data.service import get_daily
    bars, _ = get_daily(ticker)
    if bars is None or len(bars) == 0:
        return {"error": "no data"}
    last = bars.iloc[-1]
    prev = bars.iloc[-2] if len(bars) > 1 else last
    chg = (last["close"] - prev["close"]) / prev["close"] * 100
    return {
        "ticker": ticker,
        "close": float(last["close"]),
        "change_pct": round(chg, 2),
        "date": str(last.name.date()),
    }


def _handle_news(ticker: str) -> list:
    try:
        from news_pipeline import fetch_stock_news
        return fetch_stock_news(ticker)[:20]
    except Exception as e:
        return [{"error": str(e)}]


# ---------- 路由 ----------
ROUTES = {
    "search": lambda p: _handle_search(p.get("query", ""), p.get("limit", 10)),
    "quote": lambda p: _handle_quote(p.get("ticker", "")),
    "news": lambda p: _handle_news(p.get("ticker", "")),
    "ping": lambda p: {"pong": True, "time": time.time()},
}


def handle_request(req: dict) -> dict:
    """处理一条 MCP 请求。"""
    method = req.get("method", "")
    params = req.get("params", {})
    key = req.get("api_key", "anonymous")

    # 限流
    if not check_rate_limit(key):
        return {"jsonrpc": "2.0", "error": {"code": -429, "message": "rate limit"}, "id": req.get("id")}

    handler = ROUTES.get(method)
    if not handler:
        return {"jsonrpc": "2.0", "error": {"code": -32601, "message": f"unknown method: {method}"}, "id": req.get("id")}

    try:
        result = handler(params)
        return {"jsonrpc": "2.0", "result": result, "id": req.get("id")}
    except Exception as e:
        return {"jsonrpc": "2.0", "error": {"code": -500, "message": str(e)}, "id": req.get("id")}


# ---------- stdio 主循环 ----------
def serve_stdio() -> None:
    """标准 MCP stdio 协议循环。"""
    while True:
        try:
            line = input().strip()
            if not line:
                continue
            req = json.loads(line)
            resp = handle_request(req)
            print(json.dumps(resp, ensure_ascii=False), flush=True)
        except EOFError:
            break
        except Exception as e:
            print(json.dumps({"error": str(e)}, ensure_ascii=False), flush=True)


def serve_http(host: str = "127.0.0.1", port: int = 8765) -> None:
    """HTTP 模式（备选）。"""
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from urllib.parse import urlparse, parse_qs

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            try:
                req = json.loads(body)
                resp = handle_request(req)
            except Exception as e:
                resp = {"error": str(e)}
            data = json.dumps(resp, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):
            pass

    HTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    import sys
    if "--http" in sys.argv:
        serve_http()
    else:
        serve_stdio()
