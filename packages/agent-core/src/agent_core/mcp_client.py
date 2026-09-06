import json
import logging
import httpx
from typing import List, Dict, Any, Optional
from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp.client.streamable_http import streamable_http_client
from mcp.client.session import ClientSession
from agent_core.tool import BaseTool, ToolRegistry
from ai_core.models import ToolDefinition

logger = logging.getLogger(__name__)


class MCPClient:
    """
    stdio 模式 MCP 客户端连接器（保留供 Cursor / Claude Desktop 等桌面工具使用）：
    每次调用会重新 fork 子进程建立 stdio 连接，适用于本地开发调试场景。
    生产环境 quant-agent 请使用 MCPHttpClient。
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


class MCPHttpClient:
    """
    HTTP 模式 MCP 客户端（生产推荐）：
    通过 MCP Streamable HTTP 协议连接 mcp-gateway 统一网关，
    工具发现结果本地缓存，每次 call_tool 仅发一次 HTTP 请求，无进程 fork 开销。

    支持 token 透传：构造时可传入 token_getter 回调，调用时动态获取当前用户 JWT
    并通过 X-User-Token header 传递给网关，网关再转发给 common-server。
    """
    def __init__(
        self,
        url: str,
        server_name: str = "mcp-http-server",
        category: str = "quant",
        token_getter: Optional[Any] = None,
    ):
        """
        :param url: MCP Gateway 的 HTTP 端点，如 http://localhost:8050/mcp
        :param server_name: 服务名称（日志标识）
        :param category: 工具注册分类（用于 ToolRegistry 过滤）
        :param token_getter: 可选回调，签名为 () -> str，返回当前用户 JWT token
        """
        self.url = url
        self.server_name = server_name
        self.category = category
        self._token_getter = token_getter
        self._discovered_tools: Dict[str, ToolDefinition] = {}
        self._initialized: bool = False

    def _extra_headers(self) -> Dict[str, str]:
        """构造额外请求头，支持 token 透传"""
        headers: Dict[str, str] = {}
        if self._token_getter:
            try:
                token = self._token_getter()
                if token:
                    headers["X-User-Token"] = token
            except Exception:
                pass
        return headers

    async def discover_tools(self) -> List[ToolDefinition]:
        """通过 MCP Streamable HTTP 发现工具列表（结果缓存，只需调用一次）"""
        if self._initialized and self._discovered_tools:
            return list(self._discovered_tools.values())
        try:
            async with httpx.AsyncClient(headers=self._extra_headers()) as http_client:
                async with streamable_http_client(
                    self.url, http_client=http_client
                ) as (read_stream, write_stream, _):
                    async with ClientSession(read_stream, write_stream) as session:
                        await session.initialize()
                        mcp_tools_res = await session.list_tools()

                        tools: List[ToolDefinition] = []
                        for t in mcp_tools_res.tools:
                            raw_schema = getattr(t, "inputSchema", None) or getattr(t, "input_schema", None) or {}
                            tool_def = ToolDefinition(
                                name=t.name,
                                description=t.description or f"MCP tool: {t.name}",
                                parameters=raw_schema if isinstance(raw_schema, dict) else {}
                            )
                            tools.append(tool_def)
                            self._discovered_tools[t.name] = tool_def

                        self._initialized = True
                        logger.info(
                            "MCPHttpClient: discovered %d tools from '%s' (%s)",
                            len(tools), self.server_name, self.url
                        )
                        return tools
        except Exception as e:
            logger.error("MCPHttpClient: failed to discover tools from '%s': %s", self.url, e)
            return []

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        """通过 MCP Streamable HTTP 调用指定工具（无进程 fork，纯 HTTP 请求）"""
        try:
            async with httpx.AsyncClient(headers=self._extra_headers()) as http_client:
                async with streamable_http_client(
                    self.url, http_client=http_client
                ) as (read_stream, write_stream, _):
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
            logger.error(
                "MCPHttpClient: tool '%s' call failed on '%s': %s",
                name, self.url, e
            )
            return f"Error executing MCP tool '{name}': {str(e)}"

    async def register_to(self, registry: ToolRegistry) -> List[BaseTool]:
        """将从网关发现的 MCP 工具注册到本地 ToolRegistry"""
        tool_defs = await self.discover_tools()
        registered: List[BaseTool] = []

        for defn in tool_defs:
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
