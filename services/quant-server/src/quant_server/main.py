from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from quant_server.api.health import router as health_router
from quant_server.api.strategies import router as strategies_router
from quant_server.api.backtest import router as backtest_router
from quant_server.api.sandbox import router as sandbox_router
from quant_server.api.market import router as market_router

app = FastAPI(
    title="Quant Platform API",
    description="Full-stack quantitative system API gateway, backtest engine, and strategy manager",
    version="0.1.0",
)

# 开启跨域访问 (方便前端 Vue3 / 移动端调试)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载路由
app.include_router(health_router, prefix="/api/v1", tags=["Health"])
app.include_router(strategies_router, prefix="/api/v1", tags=["Strategies"])
app.include_router(backtest_router, prefix="/api/v1", tags=["Backtest"])
app.include_router(sandbox_router, prefix="/api/v1", tags=["Sandbox"])
app.include_router(market_router, prefix="/api/v1/market", tags=["Market"])

@app.get("/")
def root():
    return {
        "message": "Welcome to Quant System API Gateway",
        "docs_url": "/docs"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("quant_server.main:app", host="0.0.0.0", port=8080, reload=True)
