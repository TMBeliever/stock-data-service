from contextlib import asynccontextmanager
import logging
from fastapi import FastAPI, Request, WebSocket, status
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from api_gateway.config import settings
from api_gateway.auth import resolve_auth_context
from api_gateway.proxy import (
    forward_request,
    resolve_upstream_target,
    close_http_client,
    get_http_client,
)
from api_gateway.ws_proxy import forward_websocket

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
)
logger = logging.getLogger("api_gateway")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"🚀 Quant System API Gateway 启动中... 运行端口: {settings.PORT}")
    get_http_client()
    yield
    logger.info("🛑 Quant System API Gateway 正在优雅退出...")
    await close_http_client()


app = FastAPI(
    title="Quant System Unified API Gateway",
    description="统一 API 业务网关：身份识别、安全注入、跨域守卫与动态路由反向代理",
    version="0.1.0",
    lifespan=lifespan,
)

# 1. 统一全局 CORS 跨域治理
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["Gateway System"])
async def gateway_health():
    """网关自身健康检查探针"""
    return {
        "status": "healthy",
        "service": "api-gateway",
        "environment": settings.ENVIRONMENT,
        "routes": {
            "common_server": settings.COMMON_SERVER_URL,
            "quant_server": settings.QUANT_SERVER_URL,
            "quant_agent": settings.QUANT_AGENT_URL,
            "ai_core": settings.AI_CORE_URL,
            "stock_data": settings.STOCK_DATA_URL,
            "asset_server": settings.ASSET_SERVER_URL,
        },
    }


# 2. WebSocket 全双工通道透传
@app.websocket("/ws/{full_path:path}")
async def websocket_gateway(websocket: WebSocket, full_path: str):
    await forward_websocket(websocket, f"/ws/{full_path}")


# 3. 统一全局 HTTP 路由接管与分发处理
@app.api_route("/{full_path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"])
async def gateway_dispatch(request: Request, full_path: str):
    path = "/" + full_path

    # OPTIONS 预检请求直接通过 CORS 中间件返回
    if request.method == "OPTIONS":
        return JSONResponse(content={"message": "ok"})

    # 1. 统一身份鉴权与清洗注入 (基于漏斗策略决策)
    auth_ok, err_status, err_msg, forward_headers = resolve_auth_context(request)
    if not auth_ok:
        logger.warning(f"[{err_status}] 拦截未授权访问: {request.method} {path} - {err_msg}")
        return JSONResponse(
            status_code=err_status,
            content={
                "code": "UNAUTHORIZED" if err_status == 401 else "FORBIDDEN",
                "detail": err_msg or "无权访问当前端点",
                "path": path,
            },
            headers={"WWW-Authenticate": "Bearer"} if err_status == 401 else None,
        )

    # 2. 确定下游转发微服务目标
    target_base, target_path = resolve_upstream_target(path)

    # 3. 执行异步转发
    return await forward_request(request, forward_headers, target_base, target_path)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api_gateway.main:app", host=settings.HOST, port=settings.PORT, reload=True)
