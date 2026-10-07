# -*- coding: utf-8 -*-
"""MCP Server：把疏影·知微的工具层暴露为标准 MCP 协议（stdio / HTTP 双模式）。

一旦被外部 Agent 生态（Cursor / Claude Desktop / Cline / 自建 Agent）接入，
本程序就从"一个桌面应用"变成"金融数据与分析能力的提供者"。

双模式设计（调研 MCP 2026 现状后的选择）：
- **stdio**：本地子进程模式，客户端直连 stdin/stdout。默认、零配置、无网络暴露。
- **Streamable HTTP**：单端点（/mcp）的远程模式。**注意**：旧的 HTTP+SSE
  双端点传输自 2025-03-26 起已废弃，不要再写 ``transport="sse"``。

三条容易踩的坑，本实现已规避：
1. **stdout 只能出现 JSON-RPC**：任何日志/诊断都必须走 stderr（logging 默认即
    stderr），否则会污染协议流，客户端直接解析失败。
2. **错误要"对模型可读"**：工具失败返回结构化错误文本，而不是栈回溯——
    模型读栈只会浪费 context，读错误原因才可能自我纠正。
3. **HTTP 模式鉴权**：远程暴露意味着任何人可调用，故默认只监听 127.0.0.1。

启用完整 FastMCP 能力（可选，需用户手动执行）：
    pip install fastmcp
未安装时自动降级：stdio 用内置 JSON-RPC 子集，HTTP 用 FastAPI 单端点实现。
"""
from __future__ import annotations

import json
import logging
import os
import sys
from typing import Any, Dict, List, Optional

# 支持直接从仓库根目录运行：python -B agent\mcp_server.py
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

log = logging.getLogger("stockai.agent.mcp")

try:
    from fastmcp import FastMCP
    HAVE_FASTMCP = True
except Exception:  # noqa: BLE001
    HAVE_FASTMCP = False

PROTOCOL_VERSION = "2025-06-18"
SERVER_INFO = {"name": "ShuyingInsight", "version": "1.1.0"}


def _registry():
    """工具注册表（模块一后的统一入口，含图表 AI 控制面）。"""
    from tools import get_registry
    return get_registry()


def _tool_schemas() -> List[Dict[str, Any]]:
    """工具 JSON Schema 列表（兼容旧调用方与测试）。"""
    return _registry().mcp_tools()


# ---------------------------------------------------------------------------
# stdio：内置 JSON-RPC 2.0 子集（零依赖）
# ---------------------------------------------------------------------------
def handle_request(req: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """处理一条 JSON-RPC 请求，返回响应（通知类返回 None）。"""
    rid = req.get("id")
    method = req.get("method") or ""
    params = req.get("params") or {}

    if method == "initialize":
        return {"jsonrpc": "2.0", "id": rid, "result": {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": SERVER_INFO,
            "instructions": ("疏影·知微金融数据工具集：行情/指标/新闻/回测/检索/"
                             "图表控制面。所有输出为客观数据与历史统计，"
                             "不构成投资建议，不提供目标价与收益承诺。")}}

    if method == "ping":
        return {"jsonrpc": "2.0", "id": rid, "result": {}}

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": rid,
                "result": {"tools": _registry().mcp_tools()}}

    if method == "tools/call":
        name = params.get("name", "")
        args = params.get("arguments") or {}
        res = _registry().call(name, args)
        payload = res.to_envelope()
        return {"jsonrpc": "2.0", "id": rid, "result": {
            "content": [{"type": "text",
                         "text": json.dumps(payload, ensure_ascii=False, default=str)}],
            "structuredContent": payload,
            "isError": not res.ok}}

    if method.startswith("notifications/"):
        return None

    return {"jsonrpc": "2.0", "id": rid,
            "error": {"code": -32601, "message": f"method not found: {method}"}}


def run_stdio() -> int:
    """stdio 主循环：逐行读取 JSON-RPC，逐行回写（stdout 只写协议报文）。"""
    log.info("MCP stdio 服务启动（内置 JSON-RPC 子集）")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except Exception:  # noqa: BLE001
            sys.stdout.write(json.dumps({
                "jsonrpc": "2.0", "id": None,
                "error": {"code": -32700, "message": "parse error"}}) + "\n")
            sys.stdout.flush()
            continue
        resp = handle_request(req)
        if resp is None:
            continue
        sys.stdout.write(json.dumps(resp, ensure_ascii=False, default=str) + "\n")
        sys.stdout.flush()
    return 0


# ---------------------------------------------------------------------------
# FastMCP 完整服务（安装 fastmcp 后可用）
# ---------------------------------------------------------------------------
def _dynamic_wrapper(spec):
    """按 Pydantic 输入模型动态生成带类型注解的包装函数。

    FastMCP 通过"函数签名 + 注解"生成 JSON Schema，且不支持 **kwargs，
    因此必须把字段摊平成具名参数（白名单拼接，字段名来自模型定义）。
    """
    func = spec.func
    model = spec.input_model
    ns: Dict[str, Any] = {"_fn": func}
    if model is None:
        def _w() -> dict:
            return _registry().call(spec.name, {}).to_envelope()
        _w.__name__ = spec.name
        _w.__doc__ = spec.description
        return _w

    parts: List[str] = []
    for i, (fname, f) in enumerate(model.model_fields.items()):
        ns[f"_a{i}"] = f.annotation
        dflt = f.get_default(call_default_factory=True)
        from pydantic_core import PydanticUndefined
        if f.is_required() or dflt is PydanticUndefined:
            parts.append(f"{fname}: _a{i}")
        else:
            ns[f"_d{i}"] = dflt
            parts.append(f"{fname}: _a{i} = _d{i}")
    sig = ", ".join(parts)
    kwargs = ", ".join(f"{fname}={fname}"
                       for fname in model.model_fields.keys())
    src = (f"def _w({sig}) -> dict:\n"
           f"    return _registry().call({spec.name!r}, dict({kwargs or '**{}'})).to_envelope()\n")
    ns["_registry"] = _registry
    exec(src, ns)  # noqa: S102 - 仅拼接模型字段名与序号，不含外部输入
    _w = ns["_w"]
    _w.__name__ = spec.name
    _w.__doc__ = spec.description
    return _w


def build_fastmcp_server():
    """构造 FastMCP 服务（工具来自统一注册表）。"""
    if not HAVE_FASTMCP:
        raise RuntimeError("fastmcp 未安装")
    mcp = FastMCP("ShuyingInsight", version=SERVER_INFO["version"],
                  instructions=(
                      "疏影·知微金融数据工具集：行情/指标/新闻/回测/检索/图表控制面。"
                      "所有输出为客观数据与历史统计，不构成投资建议。"))
    for spec in _registry().specs():
        mcp.tool(name=spec.name, description=spec.description)(
            _dynamic_wrapper(spec))
    return mcp


# ---------------------------------------------------------------------------
# HTTP：Streamable HTTP 单端点（fastmcp 优先，否则 FastAPI 兜底）
# ---------------------------------------------------------------------------
def build_http_app():
    """用 FastAPI 实现 Streamable HTTP 单端点（fastmcp 缺失时的兜底）。"""
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse

    app = FastAPI(title="ShuyingInsight MCP", version=SERVER_INFO["version"])

    @app.get("/health")
    def health() -> dict:
        return {"ok": True, "server": SERVER_INFO,
                "tools": len(_registry().names()), "transport": "streamable-http"}

    @app.post("/mcp")
    async def mcp_endpoint(req: Request):
        try:
            body = await req.json()
        except Exception:  # noqa: BLE001
            return JSONResponse({"jsonrpc": "2.0", "id": None,
                                 "error": {"code": -32700, "message": "parse error"}})
        # 兼容批量请求（JSON-RPC batch）
        if isinstance(body, list):
            out = [r for r in (handle_request(x) for x in body) if r is not None]
            return JSONResponse(out)
        resp = handle_request(body)
        if resp is None:
            return JSONResponse({})
        return JSONResponse(resp)

    return app


def serve(transport: str = "stdio", host: str = "127.0.0.1",
          port: int = 8765) -> int:
    """启动 MCP Server。

    transport="stdio"          本地子进程模式（默认）
    transport="http"           Streamable HTTP，监听 127.0.0.1（默认，不对外暴露）
    """
    if transport == "http":
        if HAVE_FASTMCP:
            mcp = build_fastmcp_server()
            log.info("MCP HTTP 服务启动于 http://%s:%d/mcp", host, port)
            for t in ("streamable-http", "http"):
                try:
                    mcp.run(transport=t, host=host, port=port, show_banner=False)
                    return 0
                except TypeError:
                    continue
            return 2
        try:
            import uvicorn
        except Exception:  # noqa: BLE001
            log.warning("HTTP 模式需要 fastmcp 或 uvicorn；请手动执行 pip install fastmcp")
            return 2
        app = build_http_app()
        log.info("MCP HTTP 服务启动于 http://%s:%d/mcp（FastAPI 兜底）", host, port)
        uvicorn.run(app, host=host, port=port, log_level="warning")
        return 0

    if HAVE_FASTMCP:
        log.info("MCP stdio 服务启动（fastmcp）")
        build_fastmcp_server().run(transport="stdio", show_banner=False)
        return 0
    return run_stdio()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(levelname)s %(name)s: %(message)s")
    _t = os.environ.get("MCP_TRANSPORT", "stdio")
    _p = int(os.environ.get("MCP_PORT", "8765"))
    _h = os.environ.get("MCP_HOST", "127.0.0.1")
    sys.exit(serve(transport=_t, host=_h, port=_p))
