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
    # 命令可执行程序名称或绝对路径 (例如 'claude', 'codex', 或本地自定义 agent cli)
    CLI_EXECUTABLE: str = "claude"
    # 参数模板：支持 {prompt} 占位符，若无 {prompt} 则通过标准输入 stdin 管道传入
    CLI_ARGS: List[str] = ["-p", "{prompt}"]
    CLI_TIMEOUT: float = 120.0
    CLI_CWD: Optional[str] = None

    model_config = SettingsConfigDict(env_prefix="AI_", case_sensitive=False)

ai_config = AIConfig()
