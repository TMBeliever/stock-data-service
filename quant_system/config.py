import os
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

class QuantConfig(BaseSettings):
    """量化系统全局配置"""
    # stock-data 数据服务 HTTP 地址
    DATA_SERVICE_HTTP: str = "http://localhost:8000"
    
    # stock-data 数据服务 WebSocket 地址
    DATA_SERVICE_WS: str = "ws://localhost:8000/ws/market"
    
    # stock-data 本地工程路径 (用于 Zero-Copy SDK 直连，优先于 HTTP)
    STOCK_DATA_LOCAL_PATH: str = str(Path(__file__).resolve().parent.parent.parent / "stock-data")
    
    # 默认初始资金 (CNY)
    INITIAL_CASH: float = 100_000.0
    
    # 环境: development / production / backtest
    ENVIRONMENT: str = "development"
    
    model_config = SettingsConfigDict(env_prefix="QUANT_", case_sensitive=False)

quant_config = QuantConfig()
