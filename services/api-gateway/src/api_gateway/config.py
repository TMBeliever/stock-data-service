from enum import Enum
from typing import List, Dict
from pydantic_settings import BaseSettings, SettingsConfigDict


class AuthPolicy(str, Enum):
    """
    网关权限策略枚举 (安全漏斗决策层)：
    - ANONYMOUS: 完全匿名公开，无需任何凭证
    - USER_JWT: 前台用户级鉴权，必须持有本系统有效 JWT
    - SERVICE_KEY: 平台级/第三方 API Key 鉴权 (如外部开发者调用)
    - OPTIONAL_JWT: 可选鉴权，带 Token 则注入真实身份，未带则作为游客放行
    - ADMIN_ONLY: 仅管理员角色放行
    """
    ANONYMOUS = "ANONYMOUS"
    USER_JWT = "USER_JWT"
    SERVICE_KEY = "SERVICE_KEY"
    OPTIONAL_JWT = "OPTIONAL_JWT"
    ADMIN_ONLY = "ADMIN_ONLY"


class GatewaySettings(BaseSettings):
    # 网关服务基础配置
    HOST: str = "0.0.0.0"
    PORT: int = 8001
    ENVIRONMENT: str = "development"

    # JWT 验签密钥 (与 common-server 保持一致)
    JWT_SECRET_KEY: str = "quant_system_common_secret_key_2026_super_secure"
    JWT_ALGORITHM: str = "HS256"

    # 下游各微服务基础内网 URL
    COMMON_SERVER_URL: str = "http://localhost:8090"
    QUANT_SERVER_URL: str = "http://localhost:8080"
    QUANT_AGENT_URL: str = "http://localhost:8060"
    AI_CORE_URL: str = "http://localhost:8070"
    STOCK_DATA_URL: str = "http://localhost:8000"
    ASSET_SERVER_URL: str = "http://localhost:8050"
    MCP_GATEWAY_URL: str = "http://localhost:8050"
    WEIXIN_BOT_URL: str = "http://localhost:8095"

    STOCK_DATA_WS_URL: str = "ws://localhost:8000"

    # 内部微服务通信互信 Key (用于向保持 key 机制的下游服务如 ai-core 证明网关身份)
    INTERNAL_AI_CORE_KEY: str = "sk-quant-agy-8f92e10c74b6"

    # CORS 跨域配置
    CORS_ORIGINS: List[str] = ["*"]

    # =========================================================================
    # 权限漏斗设计：第一层 —— 服务级默认鉴权策略 (Service-Level Defaults)
    # =========================================================================
    # AI 算力服务对外策略：当前默认 ANONYMOUS (暂时免鉴权开放，第三方直接可用)
    # 若未来对外收费或加白名单，可直接在环境变量指定 GATEWAY_SERVICE_AUTH_AI=SERVICE_KEY 或 USER_JWT
    SERVICE_AUTH_AI: AuthPolicy = AuthPolicy.ANONYMOUS
    SERVICE_AUTH_USER: AuthPolicy = AuthPolicy.USER_JWT
    SERVICE_AUTH_ASSET: AuthPolicy = AuthPolicy.USER_JWT
    SERVICE_AUTH_AGENT: AuthPolicy = AuthPolicy.USER_JWT
    SERVICE_AUTH_STOCK: AuthPolicy = AuthPolicy.ANONYMOUS
    SERVICE_AUTH_QUANT: AuthPolicy = AuthPolicy.OPTIONAL_JWT
    SERVICE_AUTH_COMMON_AUTH: AuthPolicy = AuthPolicy.ANONYMOUS
    SERVICE_AUTH_MCP: AuthPolicy = AuthPolicy.ANONYMOUS

    model_config = SettingsConfigDict(env_prefix="GATEWAY_", case_sensitive=False)


settings = GatewaySettings()
