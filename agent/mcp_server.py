# -*- coding: utf-8 -*-
"""MCP Server：把疏影·知微的工具层暴露为标准 MCP 协议。

参考 tushare-mcp-http / akbridge / FastMCP：
- fastmcp 已安装 → 完整 FastMCP（stdio / HTTP 双模式），外部客户端
  （Cursor / Claude Desktop / Cline / 豆包）可直接调用数据与分析工具；
- fastmcp 未安装 → 降级为纯 stdio JSON-RPC 子集（initialize /
  tools/list / tools/call），无需额外依赖即可本地联调。

启用完整能力（可选，用户手动执行）：
    pip install fastmcp
"""
from __future__ import annotations

import json
import logging
import os
import sys
from typing import Any, Dict, List

from agent.tool_defs import build_registry, call_tool

log = logging.getLogger("stockai.agent.mcp")

try:
    from fastmcp import FastMCP
    HAVE_FASTMCP = True
except Exception:  # noqa: BLE001
    HAVE_FASTMCP = False


def _tool_schemas() -> List[Dict[str, Any]]:
    reg = build_registry()
    out = []
    for name, entry in reg.items():
        schema = entry["schema"]
        out.append({
            "name": name,
            "description": entry["description"],
            "inputSchema": schema.model_json_schema() if schema else {"type": "object"},
        })
    return out


def run_stdio() -> int:
    """纯 stdio JSON-RPC 子集（fastmcp 未安装时使用）。"""
    tools = _tool_schemas()
    server_info = {"name": "ShuyingInsight", "version": "0.7.0"}
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except Exception:  # noqa: BLE001
            continue
        rid = req.get("id")
        method = req.get("method")
        params = req.get("params") or {}
        if method == "initialize":
            resp = {"jsonrpc": "2.0", "id": rid,
                    "result": {"protocolVersion": "2024-11-05",
                               "capabilities": {"tools": {}},
                               "serverInfo": server_info}}
        elif method == "tools/list":
            resp = {"jsonrpc": "2.0", "id": rid, "result": {"tools": tools}}
        elif method == "tools/call":
            name = params.get("name", "")
            args = params.get("arguments") or {}
            result = call_tool(name, args)
            content = [{"type": "text", "text": json.dumps(
                result.model_dump(), ensure_ascii=False)}]
            resp = {"jsonrpc": "2.0", "id": rid,
                    "result": {"content": content, "isError": not result.ok}}
        elif method == "notifications/initialized":
            continue
        else:
            resp = {"jsonrpc": "2.0", "id": rid,
                    "error": {"code": -32601, "message": f"method not found: {method}"}}
        sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
        sys.stdout.flush()
    return 0


def build_fastmcp_server():
    """FastMCP 完整服务（安装 fastmcp 后可用）。"""
    mcp = FastMCP("ShuyingInsight",
                  instructions=(
                      "疏影·知微金融数据工具集。所有输出为客观数据展示，"
                      "不构成投资建议。可用工具：行情、指标、新闻、回测、搜索、市场概览。"))
    reg = build_registry()
    for name, entry in reg.items():
        func = entry["func"]
        schema = entry["schema"]
        # 从 Pydantic Schema 生成参数名（FastMCP 依据函数签名，故包装一层）
        fields = list(schema.model_fields.keys()) if schema else []

        def make(fn, fnames):
            def _wrap(**kwargs):
                return fn(**kwargs)
            _wrap.__name__ = fn.__name__
            _wrap.__doc__ = fn.__doc__
            _wrap.__annotations__ = {f: object for f in fnames}
            return _wrap
        wrapped = make(func, fields)
        mcp.tool()(wrapped)
    return mcp


def serve(transport: str = "stdio", host: str = "127.0.0.1",
          port: int = 8765) -> int:
    """启动 MCP Server。

    transport="stdio"：标准输入输出模式（Claude Desktop/Cursor 等）；
    transport="http"：HTTP/SSE 模式（需 fastmcp）。
    """
    if HAVE_FASTMCP:
        mcp = build_fastmcp_server()
        if transport == "http":
            log.info("MCP HTTP 服务启动于 http://%s:%d/mcp", host, port)
            return mcp.run(transport="http", host=host, port=port)
        log.info("MCP stdio 服务启动（fastmcp）")
        return mcp.run(transport="stdio")
    if transport == "http":
        log.warning("fastmcp 未安装，HTTP 模式不可用；请手动执行 pip install fastmcp")
        return 2
    log.info("MCP stdio 服务启动（手动 JSON-RPC 子集）")
    return run_stdio()


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO)
    transport = os.environ.get("MCP_TRANSPORT", "stdio")
    sys.exit(serve(transport=transport))
