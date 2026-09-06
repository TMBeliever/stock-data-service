import os
import json
import pytest
import jwt
from pathlib import Path
from starlette.datastructures import Headers
from unittest.mock import MagicMock

from quant_agent.config import agent_config
from quant_agent.auth import decode_token, get_current_auth, UserAuth
from quant_agent.agent_engine import quant_agent
from quant_agent.admin_tools import (
    admin_inspect_system_and_services,
    admin_read_source_code,
    admin_modify_source_code,
    admin_execute_shell,
    get_admin_tool_registry
)

def create_test_token(role: str = "user", username: str = "tester") -> str:
    """生成测试专用 JWT Token"""
    payload = {
        "sub": "1001",
        "username": username,
        "role": role,
    }
    return jwt.encode(payload, agent_config.JWT_SECRET_KEY, algorithm=agent_config.JWT_ALGORITHM)

@pytest.mark.asyncio
async def test_auth_extraction():
    """测试 JWT 提取与权限判定"""
    # 1. 匿名用户 / 无 Header
    req_anonymous = MagicMock()
    req_anonymous.headers = Headers({})
    auth_anon = await get_current_auth(req_anonymous)
    assert not auth_anon.is_admin
    assert auth_anon.role == "guest"

    # 2. 普通用户 Token
    user_token = create_test_token(role="user", username="alice")
    req_user = MagicMock()
    req_user.headers = Headers({"authorization": f"Bearer {user_token}"})
    auth_user = await get_current_auth(req_user)
    assert not auth_user.is_admin
    assert auth_user.username == "alice"
    assert auth_user.role == "user"

    # 3. 超级管理员 Token
    admin_token = create_test_token(role="admin", username="superadmin")
    req_admin = MagicMock()
    req_admin.headers = Headers({"authorization": f"Bearer {admin_token}"})
    auth_admin = await get_current_auth(req_admin)
    assert auth_admin.is_admin
    assert auth_admin.username == "superadmin"
    assert auth_admin.role == "admin"

def test_dynamic_tool_registry_rbac():
    """测试不同角色的动态工具隔离策略"""
    # 普通用户仅包含 quant 分类或通用工具，严禁暴露 admin 工具
    user_registry = quant_agent.get_active_tool_registry(is_admin=False)
    user_tool_names = [t.name for t in user_registry.list_tools()]
    assert "validate_strategy_code" in user_tool_names
    assert "admin_inspect_system_and_services" not in user_tool_names
    assert "admin_modify_source_code" not in user_tool_names
    assert "admin_docker_manage" not in user_tool_names
    assert "admin_execute_shell" not in user_tool_names

    # 超级管理员在 quant 投研场景下：物理屏蔽 admin 工具，防止大模型幻觉与乱翻源码
    admin_quant_reg = quant_agent.get_active_tool_registry(is_admin=True, scope="quant")
    admin_quant_tools = [t.name for t in admin_quant_reg.list_tools()]
    assert "validate_strategy_code" in admin_quant_tools
    assert "get_user_watchlists" in admin_quant_tools
    assert "get_user_strategies" in admin_quant_tools
    assert "run_backtest_fast" in admin_quant_tools
    assert "admin_inspect_system_and_services" not in admin_quant_tools
    assert "admin_read_source_code" not in admin_quant_tools
    assert "admin_execute_shell" not in admin_quant_tools

    # 超级管理员在 devops 运维场景下：激活运维与 Shell 工具
    admin_devops_reg = quant_agent.get_active_tool_registry(is_admin=True, scope="devops")
    admin_devops_tools = [t.name for t in admin_devops_reg.list_tools()]
    assert "admin_inspect_system_and_services" in admin_devops_tools
    assert "admin_execute_shell" in admin_devops_tools
    assert "validate_strategy_code" not in admin_devops_tools

    # 超级管理员在 all 全栈模式下：全量工具融合
    admin_all_reg = quant_agent.get_active_tool_registry(is_admin=True, scope="all")
    admin_all_tools = [t.name for t in admin_all_reg.list_tools()]
    assert "validate_strategy_code" in admin_all_tools
    assert "admin_inspect_system_and_services" in admin_all_tools
    assert "admin_read_source_code" in admin_all_tools
    assert "admin_modify_source_code" in admin_all_tools
    assert "admin_run_tests" in admin_all_tools
    assert "admin_manage_service" in admin_all_tools
    assert "admin_docker_manage" in admin_all_tools
    assert "admin_execute_shell" in admin_all_tools

@pytest.mark.asyncio
async def test_admin_inspect_system_and_services():
    """测试系统与微服务全景体检"""
    res_str = await admin_inspect_system_and_services()
    res = json.loads(res_str)
    assert "os" in res
    assert "disk" in res
    assert "services" in res
    assert "docker" in res
    assert "quant-agent" in res["services"]
    assert "quant-server" in res["services"]

def test_admin_modify_source_code_with_preflight_rollback(tmp_path):
    """测试源码安全修改与编译失败自动回滚机制"""
    test_file = Path(agent_config.WORKSPACE_ROOT) / "services" / "quant-agent" / ".test_scratch_temp.py"
    
    try:
        # 1. 正常写入 Python 文件并成功通过语法编译
        valid_code = "def add(a: int, b: int) -> int:\n    return a + b\n"
        res_ok = admin_modify_source_code(str(test_file.relative_to(agent_config.WORKSPACE_ROOT)), valid_code)
        assert "Success" in res_ok
        assert test_file.exists()
        assert test_file.read_text(encoding="utf-8") == valid_code

        # 2. 尝试写入包含严重语法错误的代码 (缺括号或无效语法)
        broken_code = "def broken_func(:\n    return invalid syntax {"
        res_broken = admin_modify_source_code(str(test_file.relative_to(agent_config.WORKSPACE_ROOT)), broken_code)
        assert "Pre-flight Check Failed" in res_broken
        assert "Auto-Rolled Back" in res_broken

        # 3. 验证原文件完整性被保护，未被破坏
        assert test_file.read_text(encoding="utf-8") == valid_code

    finally:
        # 清理临时文件
        if test_file.exists():
            test_file.unlink()

@pytest.mark.asyncio
async def test_admin_execute_shell_security():
    """测试安全终端执行与高危自毁指令拦截"""
    # 拦截高危指令
    res_danger = await admin_execute_shell("rm -rf / --no-preserve-root")
    assert "Security Intercepted" in res_danger

    # 正常指令执行
    res_ok = await admin_execute_shell("echo 'antigravity_admin_test_passed'")
    assert "=== Shell Exit Code: 0 ===" in res_ok
    assert "antigravity_admin_test_passed" in res_ok

def test_detect_intent_scope():
    """测试意图路由器的智能分流能力"""
    from quant_agent.agent_engine import detect_intent_scope

    # 1. 普通用户永远锁定在 quant 场景
    assert detect_intent_scope("重启 docker 容器", is_admin=False) == "quant"
    assert detect_intent_scope("查看当前目录代码", is_admin=False) == "quant"

    # 2. 超管在量化投研请求下：判定为 quant
    assert detect_intent_scope("拿我的稳健组合去跑我的历史大底策略，20每年的", is_admin=True) == "quant"
    assert detect_intent_scope("查询 510300 最新市盈率与 K 线", is_admin=True) == "quant"
    assert detect_intent_scope("查看我的自选组合列表", is_admin=True) == "quant"

    # 3. 超管在系统运维或源码修改请求下：判定为 devops
    assert detect_intent_scope("检查 docker 状态并重启 quant-server", is_admin=True) == "devops"
    assert detect_intent_scope("执行 git status 并修改 agent_engine.py", is_admin=True) == "devops"
    assert detect_intent_scope("运行 pytest 测试集", is_admin=True) == "devops"

    # 4. 显式指定的 agent_mode 优先
    assert detect_intent_scope("任意消息", is_admin=True, agent_mode="devops") == "devops"
    assert detect_intent_scope("任意消息", is_admin=True, agent_mode="quant") == "quant"
    assert detect_intent_scope("任意消息", is_admin=True, agent_mode="all") == "all"
