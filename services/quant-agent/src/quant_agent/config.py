import os
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

class AgentConfig(BaseSettings):
    """量化智能体微服务配置"""
    model_config = SettingsConfigDict(env_prefix="QUANT_AGENT_", case_sensitive=True)
    
    HOST: str = "0.0.0.0"
    PORT: int = 8060
    
    # 底层通用 AI 模型网关地址
    AI_CORE_URL: str = os.getenv("AI_CORE_URL", "http://localhost:8070")
    
    # 默认模型与驱动
    DEFAULT_MODEL: str = os.getenv("AI_MODEL", "gemini-flash-lite-latest")
    DEFAULT_PROVIDER: str = os.getenv("AI_PROVIDER", "key")
    
    # 金融数据中台 stock-data 路径 (用于启动其 MCP 进程)
    STOCK_DATA_DIR: str = os.getenv(
        "STOCK_DATA_DIR",
        str((Path(__file__).resolve().parents[4] / "packages" / "stock-data").resolve())
    )
    STOCK_DATA_API_URL: str = os.getenv("STOCK_DATA_API_URL", "http://localhost:8000")
    
    # 量化回测引擎地址
    QUANT_SERVER_URL: str = os.getenv("QUANT_SERVER_URL", "http://localhost:8080")
    
    # 用户中心与策略库服务地址
    COMMON_SERVER_URL: str = os.getenv("COMMON_SERVER_URL", "http://localhost:8090")
    
    # 智能体最大思考轮数 (防止 Dead Loop)
    MAX_AGENT_STEPS: int = 8

    # JWT 鉴权密钥 (与 common-server 共享，用于验证超管身份)
    JWT_SECRET_KEY: str = os.getenv("COMMON_SECRET_KEY", "quant_system_common_secret_key_2026_super_secure")
    JWT_ALGORITHM: str = os.getenv("COMMON_ALGORITHM", "HS256")

    # 项目根工作区路径 (用于超管运维管理)
    WORKSPACE_ROOT: str = os.getenv(
        "WORKSPACE_ROOT",
        str((Path(__file__).resolve().parents[4]).resolve())
    )

agent_config = AgentConfig()
