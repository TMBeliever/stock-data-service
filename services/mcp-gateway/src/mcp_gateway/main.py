"""
MCP Gateway — 统一 MCP 数据网关 (多实例解耦架构)
========================================================
将多个微服务 REST API 聚合为分层解耦的 MCP Streamable HTTP 端点：
  1. /mcp/stock (或 /mcp/system) — 系统级金融行情与数据中台 (无需 Token, 全局共享)
  2. /mcp/user                  — 用户级自选/策略/持仓服务 (自动注入 X-User-Token JWT)
  3. /mcp                       — 全量聚合端点 (向下兼容)

其他端点：
  GET /health                   — 健康探针 (JSON, 包含各分组工具统计)
  GET /debug/tools              — 调试：按分组列出所有已注册工具 (JSON)
"""
import contextlib
import logging
from typing import Dict, Any, List

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.types import ASGIApp, Receive, Scope, Send
from mcp.server.mcpserver import MCPServer
from mcp.server.streamable_http_manager import (
    StreamableHTTPASGIApp,
    StreamableHTTPSessionManager,
)

from mcp_gateway.config import gateway_config
from mcp_gateway.tools import register_stock_tools, register_user_tools
from mcp_gateway.tools.user_data import current_user_token

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)


# ── 1. 初始化独立 MCP Server 实例 ──────────────────────────────────────────────
# (1) 系统级金融行情 MCP
stock_mcp = MCPServer("quant-mcp-stock")
register_stock_tools(stock_mcp)

# (2) 用户级数据 MCP
user_mcp = MCPServer("quant-mcp-user")
register_user_tools(user_mcp)

# (3) 全量聚合 MCP (向后兼容)
all_mcp = MCPServer("quant-mcp-gateway")
register_stock_tools(all_mcp)
register_user_tools(all_mcp)

stock_tools_count = len(stock_mcp._tool_manager._tools)
user_tools_count = len(user_mcp._tool_manager._tools)
all_tools_count = len(all_mcp._tool_manager._tools)

logger.info(
    "MCP Gateway initialized: stock=%d tools, user=%d tools, aggregate=%d tools",
    stock_tools_count, user_tools_count, all_tools_count
)


# ── 2. 创建各实例独立的 SessionManager (stateless 模式) ─────────────────────────
stock_mgr = StreamableHTTPSessionManager(stock_mcp._lowlevel_server, stateless=True)
user_mgr = StreamableHTTPSessionManager(user_mcp._lowlevel_server, stateless=True)
all_mgr = StreamableHTTPSessionManager(all_mcp._lowlevel_server, stateless=True)


# ── 3. Lifespan 管理 (协同运行多 session_manager) ──────────────────────────────
@contextlib.asynccontextmanager
async def lifespan(app: Starlette):
    async with stock_mgr.run():
        async with user_mgr.run():
            async with all_mgr.run():
                logger.info("MCP Gateway: All session managers running successfully")
                yield
                logger.info("MCP Gateway: Session managers shut down cleanly")


# ── 4. 自定义探针路由 ─────────────────────────────────────────────────────────
async def health_endpoint(request: Request) -> JSONResponse:
    """健康探针：返回网关状态及分层工具统计"""
    return JSONResponse({
        "status": "healthy",
        "service": "mcp-gateway",
        "port": gateway_config.PORT,
        "upstream": {
            "stock_data": gateway_config.STOCK_DATA_URL,
            "common_server": gateway_config.COMMON_SERVER_URL,
            "quant_server": gateway_config.QUANT_SERVER_URL,
        },
        "groups": {
            "stock": {
                "endpoint": "/mcp/stock",
                "tools_count": stock_tools_count,
                "tools": list(stock_mcp._tool_manager._tools.keys()),
            },
            "user": {
                "endpoint": "/mcp/user",
                "tools_count": user_tools_count,
                "tools": list(user_mcp._tool_manager._tools.keys()),
            },
            "aggregate": {
                "endpoint": "/mcp",
                "tools_count": all_tools_count,
            }
        },
        "total_tools": all_tools_count
    })


async def debug_tools_endpoint(request: Request) -> JSONResponse:
    """调试：按分类展示所有已注册工具"""
    def _format_tools(server: MCPServer) -> List[Dict[str, Any]]:
        result = []
        for name, tool in server._tool_manager._tools.items():
            result.append({
                "name": name,
                "description": (tool.description or "").strip().split("\n")[0],
            })
        return result

    return JSONResponse({
        "total": all_tools_count,
        "stock_tools": _format_tools(stock_mcp),
        "user_tools": _format_tools(user_mcp),
    })


# ── 5. Token 透传 Middleware ──────────────────────────────────────────────────
class TokenInjectMiddleware:
    """
    从 ASGI scope headers 提取 X-User-Token 并注入 contextvars，
    以便 user_data 工具向 common-server 发起请求时携带 JWT。
    """
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket"):
            headers = dict(scope.get("headers", []))
            token = headers.get(b"x-user-token", b"").decode("utf-8", errors="ignore")
            # 同时也支持从标准 Authorization header 中提取 Bearer token
            if not token:
                auth_header = headers.get(b"authorization", b"").decode("utf-8", errors="ignore")
                if auth_header.startswith("Bearer "):
                    token = auth_header[7:].strip()
                elif auth_header:
                    token = auth_header.strip()

            ctx_token = current_user_token.set(token)
            try:
                await self.app(scope, receive, send)
            finally:
                current_user_token.reset(ctx_token)
        else:
            await self.app(scope, receive, send)


# ── 6. 构建 Starlette 应用 ────────────────────────────────────────────────────
_stock_asgi = StreamableHTTPASGIApp(stock_mgr)
_user_asgi = StreamableHTTPASGIApp(user_mgr)
_all_asgi = StreamableHTTPASGIApp(all_mgr)

_routes = [
    # 探针与调试
    Route("/health", health_endpoint, methods=["GET", "HEAD"]),
    Route("/mcp/health", health_endpoint, methods=["GET", "HEAD"]),
    Route("/debug/tools", debug_tools_endpoint, methods=["GET"]),

    # (1) 系统级行情工具 MCP 端点
    Route("/mcp/stock", endpoint=_stock_asgi, methods=["GET", "POST"]),
    Route("/mcp/system", endpoint=_stock_asgi, methods=["GET", "POST"]),

    # (2) 用户级数据工具 MCP 端点
    Route("/mcp/user", endpoint=_user_asgi, methods=["GET", "POST"]),

    # (3) 全量兼容端点
    Route("/mcp", endpoint=_all_asgi, methods=["GET", "POST"]),
    Route("/mcp/", endpoint=_all_asgi, methods=["GET", "POST"]),
]

_starlette_app = Starlette(
    debug=False,
    routes=_routes,
    lifespan=lifespan,
)

# 使用 Token 透传中间件包装 Starlette App
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
