from typing import List, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class AssetSettings(BaseSettings):
    HOST: str = "0.0.0.0"
    PORT: int = 8040
    ENVIRONMENT: str = "development"

    # 数据库路径 (生产环境挂载到 ./data)
    DATABASE_URL: str = "sqlite+aiosqlite:///data/assets.db"

    # =========================================================================
    # 行情数据源适配器配置 (可随时切换为外部数据源)
    # 可选值: "internal" (当前默认调 stock-data 服务) | "external" | "mock"
    # =========================================================================
    MARKET_DATA_PROVIDER: str = "internal"

    # 1. 内部 stock-data 服务端点
    STOCK_DATA_URL: str = "http://localhost:8000"

    # 2. 外部第三方备用行情源配置 (预留，未来切外部服务直接填)
    EXTERNAL_MARKET_URL: Optional[str] = None
    EXTERNAL_MARKET_KEY: Optional[str] = None

    # 行情短缓存时间 (秒)，避免盘中同一秒内多次调用打满下游
    QUOTE_CACHE_TTL: int = 3
    REQUEST_TIMEOUT: float = 15.0

    # CORS
    CORS_ORIGINS: List[str] = ["*"]

    model_config = SettingsConfigDict(env_prefix="ASSET_", case_sensitive=False)


settings = AssetSettings()
