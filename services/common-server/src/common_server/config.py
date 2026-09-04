import os
from pathlib import Path
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_DB_PATH = (DATA_DIR / "common.db").as_posix()
DEFAULT_DB_URL = f"sqlite+aiosqlite:///{DEFAULT_DB_PATH}"

class Settings(BaseSettings):
    # JWT 安全签名密钥
    SECRET_KEY: str = "quant_system_common_secret_key_2026_super_secure"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # Token 有效期 7 天

    # 数据库连接 (默认使用 SQLite 异步驱动，可切 PostgreSQL)
    DATABASE_URL: str = DEFAULT_DB_URL

    # CORS 跨域配置
    CORS_ORIGINS: List[str] = ["*"]

    # 运行环境
    ENVIRONMENT: str = "development"

    model_config = SettingsConfigDict(env_prefix="COMMON_", case_sensitive=False)

settings = Settings()
