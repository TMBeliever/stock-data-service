import json
import pytest
from mcp_server import mcp

@pytest.mark.asyncio
async def test_mcp_tools_registration():
    """测试 MCP 工具注册完整度"""
    tools = await mcp.list_tools()
    tool_names = [t.name for t in tools]
    
    assert "get_realtime_quote" in tool_names
    assert "get_stock_kline" in tool_names
    assert "get_stock_valuation" in tool_names
    assert "get_stock_financials" in tool_names
    assert "get_stock_profile" in tool_names
    assert "get_stock_shareholders" in tool_names
    assert "get_market_sectors" in tool_names
    assert "get_dragon_tiger_list" in tool_names
    assert "screen_stocks" in tool_names
    assert "get_macro_treasury_yield" in tool_names
    assert "get_system_storage_status" in tool_names

@pytest.mark.asyncio
async def test_mcp_call_tool_realtime_quote():
    """测试 MCP 工具实时行情调用 (贵州茅台)"""
    res = await mcp.call_tool("get_realtime_quote", {"symbol": "600519"})
    assert res.is_error is False
    assert len(res.content) > 0
    text_content = res.content[0].text
    data = json.loads(text_content)
    assert data["count"] >= 1
    assert data["data"][0]["name"] == "贵州茅台"
    assert data["data"][0]["latest_price"] is not None
    assert data["data"][0]["latest_price"] > 1000.0

@pytest.mark.asyncio
async def test_mcp_call_tool_valuation_real():
    """测试 MCP 工具真实调用 (比亚迪估值)"""
    res = await mcp.call_tool("get_stock_valuation", {"symbol": "002594"})
    assert res.is_error is False
    assert len(res.content) > 0
    text_content = res.content[0].text
    data = json.loads(text_content)
    assert data["symbol"] == "002594.SZ.STK"
    assert data["pe_ttm"] is not None
    assert data["pe_ttm"] > 0

@pytest.mark.asyncio
async def test_mcp_call_tool_profile_real():
    """测试 MCP 工具真实调用 (比亚迪画像)"""
    res = await mcp.call_tool("get_stock_profile", {"symbol": "002594"})
    assert res.is_error is False
    text_content = res.content[0].text
    data = json.loads(text_content)
    assert data["symbol"] == "002594.SZ.STK"
    assert "比亚迪" in data["company_name"]

@pytest.mark.asyncio
async def test_mcp_call_tool_storage_real():
    """测试 MCP 工具查询系统存储状态"""
    res = await mcp.call_tool("get_system_storage_status", {})
    assert res.is_error is False
    text_content = res.content[0].text
    data = json.loads(text_content)
    assert data["is_safe"] is True
