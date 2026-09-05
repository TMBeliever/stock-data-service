import json
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field

from quant_agent.config import agent_config

logger = logging.getLogger(__name__)

# 敏感写操作/Shell/DevOps 工具清单 (处于 confirm_sensitive 模式时强制需要人工授权)
SENSITIVE_TOOLS = [
    "admin_modify_source_code",
    "admin_execute_shell",
    "admin_docker_manage",
    "admin_manage_service",
    "write_file",
    "run_command",
    "run_backtest_fast",
]

class McpServerConfig(BaseModel):
    """MCP 服务器配置模型"""
    name: str
    command: str = "uv"
    args: List[str] = Field(default_factory=list)
    cwd: Optional[str] = None
    env: Dict[str, str] = Field(default_factory=dict)
    enabled: bool = True
    category: str = "general"
    description: str = ""

class AgentRuntimeConfig(BaseModel):
    """智能体全局运行与安全配置模型"""
    execution_mode: str = "confirm_sensitive"  # 'auto' | 'confirm_sensitive' | 'confirm_all'
    default_model: str = "gemini-flash-lite-latest"
    temperature: float = 0.2
    max_steps: int = 0  # 0 为无限制 (对标 DSH)
    max_observation_chars: int = 3500
    sensitive_tools: List[str] = Field(default_factory=lambda: list(SENSITIVE_TOOLS))
    mcp_servers: List[McpServerConfig] = Field(default_factory=list)

def _get_config_file_path() -> Path:
    """获取配置文件存储路径"""
    config_dir = Path(agent_config.WORKSPACE_ROOT) / "data" / "agent_config"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / "agent_settings.json"

def get_default_mcp_servers() -> List[McpServerConfig]:
    """内置的默认 MCP 服务器"""
    return [
        McpServerConfig(
            name="stock-data-mcp",
            command="uv",
            args=["run", "python", "mcp_server.py"],
            cwd=agent_config.STOCK_DATA_DIR,
            enabled=True,
            category="quant",
            description="官方金融量化行情与多维分析数据中台 MCP 服务"
        )
    ]

class SettingsManager:
    """Agent 配置中心持久化管理器"""
    def __init__(self):
        self._config: Optional[AgentRuntimeConfig] = None
        self.load()

    def load(self) -> AgentRuntimeConfig:
        config_file = _get_config_file_path()
        if config_file.exists():
            try:
                data = json.loads(config_file.read_text(encoding="utf-8"))
                self._config = AgentRuntimeConfig.model_validate(data)
                return self._config
            except Exception as e:
                logger.error("Failed to load agent settings, falling back to defaults: %s", e)

        # 默认配置
        self._config = AgentRuntimeConfig(
            execution_mode="confirm_sensitive",
            default_model=agent_config.DEFAULT_MODEL,
            max_steps=agent_config.MAX_AGENT_STEPS,
            mcp_servers=get_default_mcp_servers()
        )
        self.save()
        return self._config

    def save(self) -> None:
        if not self._config:
            return
        config_file = _get_config_file_path()
        try:
            config_file.write_text(
                json.dumps(self._config.model_dump(), ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
        except Exception as e:
            logger.error("Failed to persist agent settings: %s", e)

    def get_config(self) -> AgentRuntimeConfig:
        if not self._config:
            return self.load()
        return self._config

    def update_config(self, updates: Dict[str, Any]) -> AgentRuntimeConfig:
        current = self.get_config().model_dump()
        current.update(updates)
        self._config = AgentRuntimeConfig.model_validate(current)
        self.save()
        return self._config

settings_manager = SettingsManager()
