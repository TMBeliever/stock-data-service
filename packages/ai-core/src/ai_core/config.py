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

    # 会话亲和性惰性温备配置 (Session-Affinity Lazy Warm Worker)
    CLI_SESSION_TTL: float = 300.0  # 闲置超过 5 分钟自动自毁回收，释放服务器内存
    CLI_SESSION_SWEEP_INTERVAL: float = 30.0  # 后台定时巡检清理周期 (秒)
    CLI_MAX_ACTIVE_SESSIONS: int = 20  # 最大同时温存的并发会话上限

    # 对外 OpenAI 兼容接口固定安全鉴权密钥 (仅授权持有该 key 的客户端调用)
    GATEWAY_API_KEY: str = "sk-quant-agy-8f92e10c74b6"

    model_config = SettingsConfigDict(env_prefix="AI_", case_sensitive=False)

ai_config = AIConfig()
