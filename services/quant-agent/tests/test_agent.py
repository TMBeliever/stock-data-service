import pytest
from httpx import AsyncClient, ASGITransport
from quant_agent.main import app

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
        # mcp-gateway 工具（get_realtime_quote 等）在有网关时动态注入，CI 环境跳过
