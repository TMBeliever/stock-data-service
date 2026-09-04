import json
import logging
import httpx
from typing import List, Dict, Any, Optional
from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp.client.session import ClientSession
from ai_core.models import ToolDefinition

from quant_agent.config import agent_config

logger = logging.getLogger(__name__)

class MCPManager:
    """
    量化智能体 MCP 工具管理器：
    动态连接 stock-data MCP 服务与相关数据节点，拉取工具 Schema 并执行远程调用。
    """
    def __init__(self):
        self._cached_tools: Optional[List[ToolDefinition]] = None
        self._server_params = StdioServerParameters(
            command="uv",
            args=["run", "python", "mcp_server.py"],
            cwd=agent_config.STOCK_DATA_DIR
        )

    async def list_tools(self, force_refresh: bool = False) -> List[ToolDefinition]:
        """异步拉取所有可用工具的 JSON Schema 定义"""
        if self._cached_tools and not force_refresh:
            return self._cached_tools

        tools: List[ToolDefinition] = []

        # 1. 从 stock-data MCP Server 动态发现工具
        try:
            async with stdio_client(self._server_params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    mcp_res = await session.list_tools()
                    for t in mcp_res.tools:
                        params_schema = getattr(t, "input_schema", None) or getattr(t, "inputSchema", None) or {}
                        tools.append(
                            ToolDefinition(
                                name=t.name,
                                description=t.description or f"Financial data tool: {t.name}",
                                parameters=params_schema if isinstance(params_schema, dict) else {}
                            )
                        )
            logger.info("Successfully discovered %d tools from stock-data MCP server", len(tools))
        except Exception as e:
            logger.error("Failed to discover tools from stock-data MCP: %s", str(e))

        # 2. 补充 quant-server 回测与沙箱验证工具 (增强 Agent 策略能力)
        tools.append(
            ToolDefinition(
                name="validate_strategy_code",
                description="校验 Python 量化策略源码的语法、BaseStrategy 规范与导入安全限制，返回诊断意见。",
                parameters={
                    "type": "object",
                    "properties": {
                        "code": {"type": "string", "description": "待诊断的 Python 策略源代码完整文本"}
                    },
                    "required": ["code"]
                }
            )
        )

        tools.append(
            ToolDefinition(
                name="run_backtest_fast",
                description="在 quant-server 沙箱中极速运行量化回测，返回总收益率、年化夏普比率、最大回撤等核心 KPI 结果。",
                parameters={
                    "type": "object",
                    "properties": {
                        "code": {"type": "string", "description": "Python 策略源代码"},
                        "symbol": {"type": "string", "description": "标的代码 (如 510300, 600519, 002594)"},
                        "start": {"type": "string", "description": "回测起始日期 YYYY-MM-DD (默认 2023-01-01)"},
                        "end": {"type": "string", "description": "回测结束日期 YYYY-MM-DD (默认 2024-01-01)"},
                        "initial_cash": {"type": "number", "description": "初始资金 (默认 100000.0)"}
                    },
                    "required": ["code", "symbol"]
                }
            )
        )

        self._cached_tools = tools
        return tools

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> str:
        """分发执行工具调用"""
        # A. quant-server 本地沙箱与回测工具
        if name == "validate_strategy_code":
            return await self._call_validate_code(arguments.get("code", ""))
        elif name == "run_backtest_fast":
            return await self._call_run_backtest(arguments)

        # B. stock-data MCP 工具调用
        try:
            async with stdio_client(self._server_params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    res = await session.call_tool(name, arguments=arguments)
                    
                    # 解析 MCP 响应文本
                    if res.content and len(res.content) > 0:
                        contents = []
                        for item in res.content:
                            if hasattr(item, "text"):
                                contents.append(item.text)
                            else:
                                contents.append(str(item))
                        return "\n".join(contents)
                    return json.dumps({"status": "success", "result": "No content returned"}, ensure_ascii=False)
        except Exception as e:
            logger.error("Error executing MCP tool '%s': %s", name, str(e))
            return json.dumps({"error": f"Tool '{name}' execution failed", "detail": str(e)}, ensure_ascii=False)

    async def _call_validate_code(self, code: str) -> str:
        """调用 quant-server 的沙箱语法检查"""
        url = f"{agent_config.QUANT_SERVER_URL}/api/v1/sandbox/validate"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(url, json={"code": code})
                return json.dumps(resp.json(), ensure_ascii=False)
        except Exception as e:
            return json.dumps({"is_valid": False, "error": f"Sandbox service unavailable: {str(e)}"}, ensure_ascii=False)

    async def _call_run_backtest(self, args: Dict[str, Any]) -> str:
        """调用 quant-server 的回测执行接口"""
        url = f"{agent_config.QUANT_SERVER_URL}/api/v1/backtest/run"
        payload = {
            "code": args.get("code", ""),
            "symbol": args.get("symbol", "510300"),
            "start": args.get("start", "2023-01-01"),
            "end": args.get("end", "2024-01-01"),
            "initial_cash": float(args.get("initial_cash", 100000.0)),
            "commission_rate": 0.0003,
            "slippage": 0.001
        }
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(url, json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    # 仅精简提取关键指标传给大模型，避免上下文超标
                    kpis = data.get("kpi", {})
                    return json.dumps({
                        "status": "success",
                        "symbol": payload["symbol"],
                        "total_return": kpis.get("total_return"),
                        "annualized_return": kpis.get("annualized_return"),
                        "sharpe_ratio": kpis.get("sharpe_ratio"),
                        "max_drawdown": kpis.get("max_drawdown"),
                        "win_rate": kpis.get("win_rate"),
                        "total_trades": kpis.get("total_trades"),
                    }, ensure_ascii=False)
                return json.dumps({"status": "failed", "detail": resp.text}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"status": "error", "error": f"Backtest engine unavailable: {str(e)}"}, ensure_ascii=False)

mcp_manager = MCPManager()
