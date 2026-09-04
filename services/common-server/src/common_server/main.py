from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from common_server.config import settings
from common_server.database import init_db
from common_server.api.auth import router as auth_router
from common_server.api.user_data import router as user_data_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时自动初始化数据库表结构
    await init_db()
    yield

app = FastAPI(
    title="Quant System Common Server",
    description="用户管理与鉴权服务 (User Management & Authentication Service)",
    version="0.1.0",
    lifespan=lifespan
)

# 配置 CORS 允许前端跨域访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册认证与用户数据路由
app.include_router(auth_router, prefix="/api/v1")
app.include_router(user_data_router, prefix="/api/v1/user", tags=["User Quant Data"])

@app.get("/health", tags=["System"])
async def health_check():
    """服务健康检查探针"""
    return {
        "status": "healthy",
        "service": "common-server",
        "environment": settings.ENVIRONMENT
    }

@app.get("/", tags=["System"])
async def root():
    return {
        "message": "Welcome to Quant System Common Server API",
        "docs": "/docs",
        "openapi": "/openapi.json"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("common_server.main:app", host="0.0.0.0", port=8090, reload=True)
