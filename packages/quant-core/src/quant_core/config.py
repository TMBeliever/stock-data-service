import os
from pydantic_settings import BaseSettings, SettingsConfigDict

class QuantConfig(BaseSettings):
    """量化系统全局配置 - 严格从基础数据服务获取"""
    # 基础数据服务 HTTP 接口地址 (经由腾讯云公网标准 Nginx 80 端口 /stock 路由)
    DATA_SERVICE_HTTP: str = "http://43.155.186.45/stock"
    
    # 基础数据服务 WebSocket 实时行情地址
    DATA_SERVICE_WS: str = "ws://43.155.186.45/stock/ws/market"
    
    # 强制跳过本地 Parquet 直连线上中台 (默认为 False 优先读取本地 0.001s 缓存)
    FORCE_REMOTE: bool = False
    
    # 默认初始资金 (CNY)
    INITIAL_CASH: float = 100_000.0
    
    # 环境: development / production / backtest
    ENVIRONMENT: str = "production"
    
    model_config = SettingsConfigDict(env_prefix="QUANT_", case_sensitive=False)

quant_config = QuantConfig()
