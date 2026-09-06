"""
MCP Gateway — 统一 MCP 数据网关
========================================================
将多个业务服务的 REST API 聚合为单一 MCP Streamable HTTP 端点，
供 quant-agent 以 HTTP MCPClient 统一接入，彻底废弃 stdio 进程 fork 模式。

端点：
  GET  /health         — 健康探针
  GET  /mcp/tools      — 调试：列出所有已注册工具
  POST /mcp            — MCP Streamable HTTP 主端点（供 MCPHttpClient 接入）

Token 透传：
  请求携带 X-User-Token header → contextvars 注入 → user_data 工具转发给 common-server
"""
import logging
from contextlib import asynccontextmanager
from contextvars import copy_context

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
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
logger.info("MCP Gateway: registered %d tools total", len(mcp._tool_manager._tools))


# ── FastAPI App ───────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "MCP Gateway starting on :%d | stock-data=%s | common-server=%s",
        gateway_config.PORT,
        gateway_config.STOCK_DATA_URL,
        gateway_config.COMMON_SERVER_URL,
    )
    yield
    # 关闭时清理 HTTP 连接池
    from mcp_gateway.tools import stock_data as sd_module
    from mcp_gateway.tools import user_data as ud_module
    if sd_module._http_client and not sd_module._http_client.is_closed:
        await sd_module._http_client.aclose()
    if ud_module._http_client and not ud_module._http_client.is_closed:
        await ud_module._http_client.aclose()
    logger.info("MCP Gateway shutdown complete")


app = FastAPI(
    title="Quant MCP Gateway",
    description="Unified MCP HTTP Gateway — aggregates stock-data, common-server and future services",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── 健康探针 ──────────────────────────────────────────────────────────────────
@app.get("/health", tags=["System"])
async def health_check():
    tools = list(mcp._tool_manager._tools.keys())
    return {
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
    }


# ── 调试端点：工具列表 ────────────────────────────────────────────────────────
@app.get("/mcp/tools", tags=["MCP Debug"])
async def list_tools():
    """列出所有已注册 MCP 工具及描述（调试用）"""
    tools = []
    for name, tool in mcp._tool_manager._tools.items():
        tools.append({
            "name": name,
            "description": (tool.description or "")[:120],
        })
    return {"total": len(tools), "tools": tools}


# ── MCP Streamable HTTP 主端点 ────────────────────────────────────────────────
@app.api_route("/mcp", methods=["GET", "POST", "DELETE"], tags=["MCP"])
async def mcp_endpoint(request: Request):
    """
    MCP Streamable HTTP 主端点。
    支持 token 透传：从 X-User-Token header 读取用户 JWT，
    通过 contextvars 注入，user_data 工具在调用 common-server 时自动携带。
    """
    # 从请求 header 提取并注入用户 token
    user_token = request.headers.get("X-User-Token", "")
    token = current_user_token.set(user_token)

    try:
        # 将请求交给 MCP Server 的 Streamable HTTP 处理器
        handler = mcp.streamable_http_app()
        return await handler(request.scope, request.receive, request._send)
    finally:
        current_user_token.reset(token)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "mcp_gateway.main:app",
        host=gateway_config.HOST,
        port=gateway_config.PORT,
        reload=False,
    )
