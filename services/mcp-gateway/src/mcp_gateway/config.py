import os
from pydantic_settings import BaseSettings, SettingsConfigDict


class GatewayConfig(BaseSettings):
    """MCP Gateway 统一配置"""
    model_config = SettingsConfigDict(env_prefix="MCP_GATEWAY_", case_sensitive=True)

    HOST: str = "0.0.0.0"
    PORT: int = 8050

    # ── 上游业务服务地址 ──────────────────────────────────────────────
    # 金融行情数据服务 (packages/stock-data)
    STOCK_DATA_URL: str = os.getenv("STOCK_DATA_API_URL", "http://localhost:8000")

    # 用户中心与策略库服务 (services/common-server)
    COMMON_SERVER_URL: str = os.getenv("COMMON_SERVER_URL", "http://localhost:8090")

    # 量化回测引擎 (services/quant-server)
    QUANT_SERVER_URL: str = os.getenv("QUANT_SERVER_URL", "http://localhost:8080")

    # ── 服务间内部鉴权 ────────────────────────────────────────────────
    INTERNAL_SERVICE_NAME: str = "mcp-gateway"


gateway_config = GatewayConfig()
