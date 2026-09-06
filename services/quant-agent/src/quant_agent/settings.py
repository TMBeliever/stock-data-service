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
    type: str = "http"  # 'http' | 'stdio'
    url: Optional[str] = None
    command: str = "uv"
    args: List[str] = Field(default_factory=list)
    cwd: Optional[str] = None
    env: Dict[str, str] = Field(default_factory=dict)
    enabled: bool = True
    group: str = "stock"  # 'stock' | 'user' | 'custom' | 'admin'
    category: str = "stock"
    description: str = ""
    allow_user_toggle: bool = True  # 是否支持普通用户自主开关切换
    disabled_tools: List[str] = Field(default_factory=list)  # 该服务下禁用的工具列表

class AgentRuntimeConfig(BaseModel):
    """智能体全局运行与安全配置模型"""
    execution_mode: str = "confirm_sensitive"  # 'auto' | 'confirm_sensitive' | 'confirm_all'
    default_model: str = "agt-gemini-3.8-flash"
    temperature: float = 0.2
    max_steps: int = 0  # 0 为无限制 (对标 DSH)
    max_observation_chars: int = 3500
    sensitive_tools: List[str] = Field(default_factory=lambda: list(SENSITIVE_TOOLS))
    admin_tools_enabled: bool = True  # 超级管理员专属系统级/DevOps运维工具调用总开关
    disabled_tools: List[str] = Field(default_factory=list)  # 系统级运维或全局禁用的工具列表
    mcp_servers: List[McpServerConfig] = Field(default_factory=list)

def _get_config_file_path() -> Path:
    """获取配置文件存储路径"""
    config_dir = Path(agent_config.WORKSPACE_ROOT) / "data" / "agent_config"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / "agent_settings.json"

def get_default_mcp_servers() -> List[McpServerConfig]:
    """内置的默认 MCP 服务器：金融行情数据中台与用户专属数据服务"""
    base_mcp_url = agent_config.MCP_GATEWAY_URL.rstrip('/')
    # 动态确定各服务独立挂载端点
    if base_mcp_url.endswith("/stock") or base_mcp_url.endswith("/system"):
        stock_url = base_mcp_url
        user_url = base_mcp_url.rsplit('/', 1)[0] + "/user"
    elif base_mcp_url.endswith("/user"):
        stock_url = base_mcp_url.rsplit('/', 1)[0] + "/stock"
        user_url = base_mcp_url
    else:
        stock_url = f"{base_mcp_url}/stock"
        user_url = f"{base_mcp_url}/user"

    return [
        McpServerConfig(
            name="mcp-stock",
            type="http",
            url=stock_url,
            enabled=True,
            group="stock",
            category="stock",
            description="官方金融行情与多维分析数据中台 (实时报价/K线/估值/财务/资金流/股东/研报/板块)",
            allow_user_toggle=True,
            disabled_tools=[]
        ),
        McpServerConfig(
            name="mcp-user",
            type="http",
            url=user_url,
            enabled=True,
            group="user",
            category="user",
            description="用户专属自选股与量化策略数据服务 (自选股/策略库/实盘持仓)",
            allow_user_toggle=True,
            disabled_tools=[]
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

                # 自动清理旧版残留的 stock-data-mcp，绝不让其出现在第三方扩展服务中
                clean_servers = [s for s in self._config.mcp_servers if s.name != "stock-data-mcp"]
                server_names = {s.name for s in clean_servers}
                defaults = get_default_mcp_servers()
                for d in defaults:
                    if d.name not in server_names:
                        clean_servers.insert(0 if d.name == "mcp-stock" else 1, d)
                
                # 规范化 group 字段
                for s in clean_servers:
                    if s.name == "mcp-stock" and s.group != "stock":
                        s.group = "stock"
                    elif s.name == "mcp-user" and s.group != "user":
                        s.group = "user"

                need_save = len(clean_servers) != len(self._config.mcp_servers) or "mcp-stock" not in server_names
                self._config.mcp_servers = clean_servers
                if need_save:
                    self.save()

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
