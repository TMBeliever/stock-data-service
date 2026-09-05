import json
import logging
from typing import List, Dict, Any, Optional
from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp.client.session import ClientSession
from agent_core.tool import BaseTool, ToolRegistry
from ai_core.models import ToolDefinition

logger = logging.getLogger(__name__)

class MCPClient:
    """
    通用 MCP (Model Context Protocol) 客户端连接器：
    管理与任意标准 MCP Server 的会话生命周期，自动发现工具并注册至 ToolRegistry
    """
    def __init__(
        self,
        command: str,
        args: List[str],
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
        server_name: str = "mcp_server",
        category: str = "mcp"
    ):
        self.command = command
        self.args = args
        self.cwd = cwd
        self.env = env
        self.server_name = server_name
        self.category = category
        self._discovered_tools: Dict[str, ToolDefinition] = {}

    def _get_server_params(self) -> StdioServerParameters:
        return StdioServerParameters(
            command=self.command,
            args=self.args,
            env=self.env,
            cwd=self.cwd
        )

    async def discover_tools(self) -> List[ToolDefinition]:
        """连接 MCP Server 并拉取所有注册的工具 Schema"""
        params = self._get_server_params()
        try:
            async with stdio_client(params) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    mcp_tools_res = await session.list_tools()
                    
                    tools: List[ToolDefinition] = []
                    for t in mcp_tools_res.tools:
                        raw_schema = getattr(t, "input_schema", None) or getattr(t, "inputSchema", None) or {}
                        tool_def = ToolDefinition(
                            name=t.name,
                            description=t.description or f"MCP tool: {t.name}",
                            parameters=raw_schema if isinstance(raw_schema, dict) else {}
                        )
                        tools.append(tool_def)
                        self._discovered_tools[t.name] = tool_def
                    
                    logger.info("Discovered %d tools from MCP server '%s'", len(tools), self.server_name)
                    return tools
        except Exception as e:
            logger.error("Failed to discover tools from MCP server '%s': %s", self.server_name, e)
            return []

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        """通过 MCP 协议远程调用指定工具"""
        params = self._get_server_params()
        try:
            async with stdio_client(params) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    res = await session.call_tool(name=name, arguments=arguments)
                    
                    if not res.content:
                        return "Success: Tool executed with no content returned."

                    text_parts = []
                    for item in res.content:
                        if hasattr(item, "text"):
                            text_parts.append(item.text)
                        else:
                            text_parts.append(str(item))

                    combined = "\n".join(text_parts)
                    try:
                        return json.loads(combined)
                    except Exception:
                        return combined
        except Exception as e:
            logger.error("MCP tool '%s' call failed on server '%s': %s", name, self.server_name, e)
            return f"Error executing MCP tool '{name}': {str(e)}"

    async def register_to(self, registry: ToolRegistry) -> List[BaseTool]:
        """将发现的 MCP 工具作为 BaseTool 挂载到统一工具注册表中"""
        tool_defs = await self.discover_tools()
        registered: List[BaseTool] = []

        for defn in tool_defs:
            # 闭包绑定当前工具名称与执行函数
            tool_name = defn.name
            
            async def _executor(_tname=tool_name, **kwargs):
                return await self.call_tool(_tname, kwargs)

            tool_obj = BaseTool(
                name=defn.name,
                description=defn.description,
                parameters=defn.parameters,
                category=self.category,
                func=_executor
            )
            registry.register(tool_obj)
            registered.append(tool_obj)

        return registered
