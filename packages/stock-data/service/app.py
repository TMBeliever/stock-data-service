import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from config import settings
from service.routes import kline, meta, system, valuation, financials, market_data, advanced, ws, snapshot, dividends, margin, analyst

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时确保数据库与目录就绪并执行轻量级存储元数据对齐 Reconcile
    print(f"[{settings.APP_NAME}] Initializing database and directories...")
    from storage.parquet_manager import parquet_mgr
    reconcile_res = parquet_mgr.reconcile_storage_metadata()
    if reconcile_res["cleaned_orphans"] > 0 or reconcile_res["restored_records"] > 0:
        print(f"[{settings.APP_NAME}] Storage metadata reconciled: {reconcile_res}")
    from service.scheduler import scheduler
    daemon_task = asyncio.create_task(scheduler.run_daemon())
    yield
    scheduler.is_running = False
    daemon_task.cancel()
    print(f"[{settings.APP_NAME}] Shutting down...")

app = FastAPI(
    title=settings.APP_NAME,
    description="面向股票分析、量化交易与策略回测的全球股票数据服务 (50GB空间极致优化架构)",
    version="1.0.0",
    lifespan=lifespan
)

# 允许跨域 (通配符 origins 时严格按照规范设置 allow_credentials=False 杜绝浏览器安全警告)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(kline.router)
app.include_router(snapshot.router)
app.include_router(meta.router)
app.include_router(system.router)
app.include_router(valuation.router)
app.include_router(financials.router)
app.include_router(market_data.router)
app.include_router(advanced.router)
app.include_router(dividends.router)
app.include_router(margin.router)
app.include_router(analyst.router)
app.include_router(ws.router)

@app.get("/")
def root():
    return {
        "service": settings.APP_NAME,
        "status": "online",
        "docs_url": "/docs"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("service.app:app", host=settings.HOST, port=settings.PORT, reload=settings.DEBUG)
