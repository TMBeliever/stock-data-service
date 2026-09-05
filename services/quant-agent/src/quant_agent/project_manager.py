from pathlib import Path
from agent_core.workspace import (
    WorkspaceManager,
    Project,
    ProjectSession,
    SessionMessage,
    get_default_preset_projects,
)
from quant_agent.config import agent_config

# 初始化量化系统项目工作空间管理器 (基于 agent-core 通用能力)
storage_dir = Path(agent_config.WORKSPACE_ROOT) / "data" / "codex_workspace"
project_manager = WorkspaceManager(
    storage_dir=storage_dir,
    workspace_root=agent_config.WORKSPACE_ROOT
)

__all__ = [
    "project_manager",
    "Project",
    "ProjectSession",
    "SessionMessage",
    "get_default_preset_projects",
]
