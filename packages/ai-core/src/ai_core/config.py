from typing import List, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict

class AIConfig(BaseSettings):
    """AI 基础设施全局配置"""
    # 默认选用的提供方 ('key' 或 'cli')
    DEFAULT_PROVIDER: str = "key"

    # API Key 驱动配置 (默认使用用户搭建在 43.155.186.45:3000 的大模型中台网关)
    OPENAI_BASE_URL: str = "http://43.155.186.45:3000/v1"
    OPENAI_API_KEY: str = "sk-W91gp63k2tmArgtL8wxIMoQaYj8CmFtumeF9T34xSpuIZj34"
    OPENAI_MODEL: str = "minimax/minimax-m3:free"
    HTTP_TIMEOUT: float = 90.0
    HTTP_MAX_RETRIES: int = 2

    # CLI 命令行驱动配置
    # 命令可执行程序名称或绝对路径 (例如 'agy', 'claude', 'codex', 或本地自定义 agent cli)
    CLI_EXECUTABLE: str = "agy"
    # 参数模板：支持 {prompt} 占位符，默认带上 --dangerously-skip-permissions 防止无头进程挂起
    CLI_ARGS: List[str] = ["-p", "{prompt}", "--dangerously-skip-permissions"]
    CLI_TIMEOUT: float = 120.0
    CLI_CWD: Optional[str] = None

    # 独占预热待命池配置 (Pre-warmed Standby Pool - 彻底无状态 + 零冷启动)
    CLI_STANDBY_POOL_SIZE: int = 4  # 活跃期待命 4 个已预热就绪的进程 (~640MB，随调随走)
    CLI_MAX_CONCURRENCY: int = 4    # 系统允许最大并发推演进程上限 (4 个完全独立物理进程)
    CLI_SPAWN_STAGGER_DELAY: float = 2.0  # 温和启动间隔 (秒)：错峰逐个拉起，杜绝 CPU 瞬间打满
    CLI_POOL_IDLE_TIMEOUT: float = 300.0  # 闲置超过 5 分钟无请求自动销毁待命进程，内存归零 (Scale-to-Zero)

    # 对外 OpenAI 兼容接口固定安全鉴权密钥 (仅授权持有该 key 的客户端调用)
    GATEWAY_API_KEY: str = "sk-quant-agy-8f92e10c74b6"

    model_config = SettingsConfigDict(env_prefix="AI_", case_sensitive=False)

ai_config = AIConfig()
