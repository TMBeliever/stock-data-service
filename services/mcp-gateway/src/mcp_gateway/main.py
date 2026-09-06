"""
MCP Gateway — 统一 MCP 数据网关
========================================================
将多个业务服务的 REST API 聚合为单一 MCP Streamable HTTP 端点，
供 quant-agent 以 HTTP MCPClient 统一接入，彻底废弃 stdio 进程 fork 模式。

端点：
  GET  /health         — 健康探针（JSON）
  GET  /debug/tools    — 调试：列出所有已注册工具（JSON）
  *    /mcp            — MCP Streamable HTTP 主端点（供 MCPHttpClient 接入）

Token 透传：
  请求携带 X-User-Token header → ASGI middleware → contextvars 注入
  → user_data 工具在调用 common-server 时自动携带 JWT

架构说明：
  MCPServer.streamable_http_app() 接受 custom_starlette_routes 参数，
  可以在 MCP Starlette 内部直接加入额外路由（/health、/debug 等）。
  整个 Starlette app 作为 uvicorn 主 app 运行，lifespan 由 MCP 管理。
  TokenInjectMiddleware 包装整个 app，注入 contextvars token。
"""
import json
import logging
from typing import Callable

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.types import ASGIApp, Receive, Scope, Send
from mcp.server.mcpserver import MCPServer

from mcp_gateway.config import gateway_config
from mcp_gateway.tools import register_stock_tools, register_user_tools
from mcp_gateway.tools.user_data import current_user_token

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)


# ── MCP Server 初始化 ─────────────────────────────────────────────────────────
mcp = MCPServer("quant-mcp-gateway")
register_stock_tools(mcp)
register_user_tools(mcp)
_tool_count = len(mcp._tool_manager._tools)
logger.info("MCP Gateway: registered %d tools total", _tool_count)


# ── Token 透传 ASGI Middleware ────────────────────────────────────────────────
class TokenInjectMiddleware:
    """
    从 ASGI scope 的 headers 中提取 X-User-Token，注入 contextvars，
    令 user_data 工具在调用 common-server 时自动携带 JWT。
    """
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket"):
            headers = dict(scope.get("headers", []))
            token = headers.get(b"x-user-token", b"").decode("utf-8", errors="ignore")
            ctx_token = current_user_token.set(token)
            try:
                await self.app(scope, receive, send)
            finally:
                current_user_token.reset(ctx_token)
        else:
            await self.app(scope, receive, send)


# ── 自定义路由处理器 ──────────────────────────────────────────────────────────
async def health_endpoint(request: Request) -> JSONResponse:
    """健康探针"""
    tools = list(mcp._tool_manager._tools.keys())
    return JSONResponse({
        "status": "healthy",
        "service": "mcp-gateway",
        "port": gateway_config.PORT,
        "upstream": {
            "stock_data": gateway_config.STOCK_DATA_URL,
            "common_server": gateway_config.COMMON_SERVER_URL,
            "quant_server": gateway_config.QUANT_SERVER_URL,
        },
        "tools_count": len(tools),
        "tools": tools,
    })


async def debug_tools_endpoint(request: Request) -> JSONResponse:
    """调试：列出所有已注册 MCP 工具"""
    tools = []
    for name, tool in mcp._tool_manager._tools.items():
        tools.append({
            "name": name,
            "description": (tool.description or "")[:120],
        })
    return JSONResponse({"total": len(tools), "tools": tools})


# ── 构建 Starlette App ────────────────────────────────────────────────────────
# 使用 custom_starlette_routes 将 /health 和 /debug 嵌入 MCP 的 Starlette app 中，
# 这样 MCP 自己管理 lifespan（session_manager.run()），我们只加额外路由
_custom_routes = [
    Route("/health", health_endpoint, methods=["GET", "HEAD"]),
    Route("/debug/tools", debug_tools_endpoint, methods=["GET"]),
]

# streamable_http_app 通过 lowlevel server 调用以支持 custom_starlette_routes
# MCPServer.streamable_http_app() 不暴露此参数，直接访问 _lowlevel_server
_starlette_app = mcp._lowlevel_server.streamable_http_app(
    streamable_http_path="/mcp",
    stateless_http=True,              # 无状态：每次请求独立，适合网关场景
    custom_starlette_routes=_custom_routes,
    host="0.0.0.0",                   # 允许外部连接（不限 127.0.0.1）
)

# Token 透传 Middleware 包装整个 app
app = TokenInjectMiddleware(_starlette_app)


if __name__ == "__main__":
    import uvicorn
    logger.info(
        "MCP Gateway starting on :%d | stock-data=%s | common-server=%s",
        gateway_config.PORT,
        gateway_config.STOCK_DATA_URL,
        gateway_config.COMMON_SERVER_URL,
    )
    uvicorn.run(
        "mcp_gateway.main:app",
        host=gateway_config.HOST,
        port=gateway_config.PORT,
        reload=False,
    )
