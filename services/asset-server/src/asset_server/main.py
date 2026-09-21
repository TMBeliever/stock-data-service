import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from asset_server.config import settings
from asset_server.database import init_db
from asset_server.api.routes import router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
)
logger = logging.getLogger("asset_server")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"🚀 Quant System 基础资产服务 (Asset Server) 启动中... 运行端口: {settings.PORT}")
    await init_db()
    logger.info("✓ 资产数据库表结构初始化完毕")
    yield
    logger.info("🛑 Quant System 基础资产服务正在优雅退出...")


app = FastAPI(
    title="Quant System Foundational Asset Service",
    description="全品类基础资产统一存储、可插拔行情对接与动态净资产估值核算服务",
    version="0.1.0",
    lifespan=lifespan,
)

# 跨域配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载路由
app.include_router(router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("asset_server.main:app", host=settings.HOST, port=settings.PORT, reload=True)
