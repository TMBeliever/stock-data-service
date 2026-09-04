from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="allow")

    # 服务基础设置
    APP_NAME: str = "GlobalStockDataService"
    ENV: str = "development"
    DEBUG: bool = True
    PORT: int = 8000
    HOST: str = "127.0.0.1"

    # 存储路径配置
    DATA_PATH: Path = DATA_DIR
    META_DB_PATH: Path = DATA_DIR / "metadata" / "meta.db"
    BENCHMARK_DIR: Path = DATA_DIR / "benchmarks"
    CACHE_KLINE_DIR: Path = DATA_DIR / "cache_kline"
    SNAPSHOT_DIR: Path = DATA_DIR / "snapshots"

    # 50GB 磁盘保护配置 (单位: GB)
    MAX_CACHE_SIZE_GB: float = 20.0         # 非核心 Lazy 缓存硬限额 (20GB)
    CACHE_HIGH_WATERMARK: float = 0.90      # 达到 90% (18GB) 触发报警与清理
    CACHE_LOW_WATERMARK: float = 0.60       # 清理回退目标水位 60% (12GB)
    GLOBAL_DISK_MIN_FREE_GB: float = 10.0   # 整个系统最少保留 10GB 空闲安全冗余

    # 默认缓存时间 (秒)
    IN_MEMORY_CACHE_TTL: int = 60

    # 标的空数据 (停牌/无交易) 重新验证 TTL (秒)，默认 24 小时 (86400s)
    SYMBOL_NO_DATA_TTL: int = 86400

settings = Settings()

# 确保所有目录存在
for path in [
    settings.DATA_PATH,
    settings.DATA_PATH / "metadata",
    settings.BENCHMARK_DIR,
    settings.CACHE_KLINE_DIR / "daily",
    settings.CACHE_KLINE_DIR / "minute",
    settings.SNAPSHOT_DIR,
]:
    path.mkdir(parents=True, exist_ok=True)
