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
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/agent/tools")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 10
        tool_names = [t["function"]["name"] for t in data["tools"]]
        assert "get_stock_kline" in tool_names
        assert "get_stock_valuation" in tool_names
        assert "validate_strategy_code" in tool_names
