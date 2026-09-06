import sys
from pathlib import Path
import pytest
from httpx import AsyncClient, ASGITransport
from quant_agent.main import app

# 动态确保当前测试目录在 sys.path 中，支持根目录与子目录各种 pytest 运行方式
TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from test_admin_tools import create_test_token

@pytest.mark.asyncio
async def test_health():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert data["service"] == "quant-agent"

@pytest.mark.asyncio
async def test_list_tools():
    """
    验证工具注册状态：
    - 本地内联工具（validate_strategy_code / run_backtest_fast）始终存在
    - mcp-gateway 工具（get_realtime_quote 等）在 initialize_tools() 连上网关后动态注入
      测试环境无网关，所以此处只断言本地工具
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/agent/tools")
        assert resp.status_code == 200
        data = resp.json()
        tool_names = [t["function"]["name"] for t in data["tools"]]
        # 本地沙箱工具必须存在
        assert "validate_strategy_code" in tool_names
        assert "run_backtest_fast" in tool_names

@pytest.mark.asyncio
async def test_mcp_servers_separated_listing():
    """验证 MCP 服务器分离列表返回：普通用户仅见 stock/user/other，超管额外可见系统级运维工具"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. 普通用户请求
        user_token = create_test_token(role="user", username="trader_bob")
        resp_user = await client.get(
            "/api/v1/agent/mcp/servers",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert resp_user.status_code == 200
        data_user = resp_user.json()
        names_user = [s["name"] for s in data_user["servers"]]
        assert "mcp-stock" in names_user
        assert "mcp-user" in names_user
        # 普通用户绝不能看到超管系统级运维工具项
        assert "admin-system-tools" not in names_user

        # 2. 超管请求
        admin_token = create_test_token(role="admin", username="super_admin")
        resp_admin = await client.get(
            "/api/v1/agent/mcp/servers",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert resp_admin.status_code == 200
        data_admin = resp_admin.json()
        names_admin = [s["name"] for s in data_admin["servers"]]
        assert "mcp-stock" in names_admin
        assert "mcp-user" in names_admin
        assert "admin-system-tools" in names_admin

@pytest.mark.asyncio
async def test_mcp_servers_toggle_rbac():
    """验证 MCP 开关权限：普通用户可自主切换 stock / user；超管可控制系统级运维工具；越权时拒绝"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        user_token = create_test_token(role="user", username="trader_bob")
        admin_token = create_test_token(role="admin", username="super_admin")

        # 1. 普通用户切换 mcp-user: 允许
        resp = await client.post(
            "/api/v1/agent/mcp/servers/mcp-user/toggle",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"enabled": False}
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "success"

        # 恢复状态
        await client.post(
            "/api/v1/agent/mcp/servers/mcp-user/toggle",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"enabled": True}
        )

        # 2. 普通用户尝试切换 admin-system-tools: 403 拒绝
        resp_forbidden = await client.post(
            "/api/v1/agent/mcp/servers/admin-system-tools/toggle",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"enabled": False}
        )
        assert resp_forbidden.status_code == 403

        # 3. 超管切换 admin-system-tools: 允许
        resp_admin = await client.post(
            "/api/v1/agent/mcp/servers/admin-system-tools/toggle",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"enabled": False}
        )
        assert resp_admin.status_code == 200
        assert resp_admin.json()["server"]["name"] == "admin-system-tools"
        assert resp_admin.json()["enabled"] is False

        # 恢复超管状态为 True
        await client.post(
            "/api/v1/agent/mcp/servers/admin-system-tools/toggle",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"enabled": True}
        )

@pytest.mark.asyncio
async def test_individual_tool_toggle():
    """验证单个具体工具的精细化开关：支持开启/关闭具体工具能力，验证返回与持久化生效"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        user_token = create_test_token(role="user", username="trader_bob")
        admin_token = create_test_token(role="admin", username="super_admin")

        # 1. 普通用户开关普通行情工具（如 get_realtime_quote）
        resp = await client.post(
            "/api/v1/agent/mcp/tools/get_realtime_quote/toggle",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"enabled": False, "server_name": "mcp-stock"}
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "success"
        assert resp.json()["enabled"] is False

        # 恢复开启
        resp_restore = await client.post(
            "/api/v1/agent/mcp/tools/get_realtime_quote/toggle",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"enabled": True, "server_name": "mcp-stock"}
        )
        assert resp_restore.status_code == 200
        assert resp_restore.json()["enabled"] is True

        # 2. 普通用户尝试开关系统运维工具 admin_execute_shell：403 拒绝
        resp_admin_forbidden = await client.post(
            "/api/v1/agent/mcp/tools/admin_execute_shell/toggle",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"enabled": False}
        )
        assert resp_admin_forbidden.status_code == 403

        # 3. 超级管理员开关系统运维工具 admin_execute_shell：允许
        resp_admin_ok = await client.post(
            "/api/v1/agent/mcp/tools/admin_execute_shell/toggle",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"enabled": False}
        )
        assert resp_admin_ok.status_code == 200
        assert resp_admin_ok.json()["enabled"] is False

        # 恢复开启
        await client.post(
            "/api/v1/agent/mcp/tools/admin_execute_shell/toggle",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"enabled": True}
        )


