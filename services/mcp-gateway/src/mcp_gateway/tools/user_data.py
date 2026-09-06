"""
user_data.py — 用户数据工具组
将 common-server 的用户数据 REST API 包装为 MCP 工具。
支持用户 JWT Token 透传：MCP 工具调用时通过 contextvars 注入 token，
网关在转发请求时携带 Authorization header。
"""
import json
import logging
from contextvars import ContextVar
from typing import Optional, List
import httpx

from mcp.server.mcpserver import MCPServer
from mcp_gateway.config import gateway_config

logger = logging.getLogger(__name__)

# 每个请求的用户 token 通过 contextvars 透传，线程/协程安全
current_user_token: ContextVar[str] = ContextVar("current_user_token", default="")

_http_client: Optional[httpx.AsyncClient] = None


def get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(
            base_url=gateway_config.COMMON_SERVER_URL,
            timeout=15.0,
        )
    return _http_client


def _auth_headers() -> dict:
    """构造带用户 token 的请求头"""
    headers = {"X-Internal-Service": gateway_config.INTERNAL_SERVICE_NAME}
    token = current_user_token.get()
    if token:
        headers["Authorization"] = token if token.startswith("Bearer ") else f"Bearer {token}"
    return headers


async def _call(method: str, endpoint: str, params: dict = None, json_body: dict = None) -> str:
    """调用 common-server REST API，统一错误处理"""
    try:
        client = get_http_client()
        resp = await client.request(
            method=method,
            url=endpoint,
            params=params or {},
            json=json_body,
            headers=_auth_headers()
        )
        if resp.status_code == 200:
            return json.dumps(resp.json(), ensure_ascii=False)
        return json.dumps(
            {"error": f"HTTP {resp.status_code}", "detail": resp.text},
            ensure_ascii=False
        )
    except Exception as e:
        logger.error("common-server call failed [%s %s]: %s", method, endpoint, e)
        return json.dumps({"error": "用户数据服务不可用", "detail": str(e)}, ensure_ascii=False)


def register_user_tools(mcp: MCPServer) -> None:
    """将所有用户数据工具注册到 MCP 服务端"""

    @mcp.tool()
    async def get_user_watchlists() -> str:
        """
        【核心投研数据工具】获取当前用户在平台保存的所有自选股票池与投资组合列表 (User Watchlists)。
        返回各组合名称（如 '稳健组合'、'高股息资产'、'核心资产'）、包含的标的代码列表 (symbols) 以及创建时间。
        【重要准则】当用户提及'我的组合'、'我的自选'、'稳健组合'或要求对特定组合进行回测/分析时，
        必须立即且优先调用本工具获取真实标的代码，绝对禁止翻看项目源码！
        """
        result = await _call("GET", "/api/v1/user/watchlists")
        try:
            data = json.loads(result)
            if isinstance(data, list):
                return json.dumps({"status": "success", "total": len(data), "watchlists": data}, ensure_ascii=False)
        except Exception:
            pass
        return result

    @mcp.tool()
    async def get_user_strategies(keyword: Optional[str] = None, include_code: bool = False) -> str:
        """
        【核心策略库工具】获取当前用户个人策略库中保存的自定义量化策略清单与 Python 源码。
        支持按策略名称关键词模糊查询（如 '历史大底'、'双均线'、'网格'）。
        返回匹配策略的名称 (name)、目标标的 (symbol)、策略说明与可直接运行的 Python 源码 (code)。
        【重要准则】当用户提到'我的策略'、'跑我的历史大底策略'时，必须立即调用本工具获取代码，
        严禁去文件系统或项目源码库搜索！
        :param keyword: 策略名称关键词，支持模糊匹配，如 '历史大底'、'双均线'
        :param include_code: 是否强制返回完整策略源码 (默认智能按数量判断)
        """
        result = await _call("GET", "/api/v1/user/strategies")
        try:
            strategies = json.loads(result)
            if not isinstance(strategies, list):
                return result

            # 按关键词过滤
            if keyword and str(keyword).strip():
                kw = str(keyword).strip().lower()
                strategies = [
                    s for s in strategies
                    if kw in s.get("name", "").lower() or kw in (s.get("description") or "").lower()
                ]

            # 智能紧凑投影：关键词匹配 <= 2 条或只有 1 条时，附带完整代码
            should_include_code = include_code or (keyword and len(strategies) <= 2) or (len(strategies) == 1)

            projected = []
            for s in strategies:
                item = {
                    "id": s.get("id"),
                    "name": s.get("name"),
                    "symbol": s.get("symbol"),
                    "description": s.get("description"),
                }
                if should_include_code:
                    item["code"] = s.get("code")
                else:
                    item["has_code"] = bool(s.get("code"))
                projected.append(item)

            res_dict: dict = {"status": "success", "total": len(projected), "strategies": projected}
            if not should_include_code and len(strategies) > 1:
                res_dict["note"] = (
                    "为避免上下文过载，策略代码未全量展开。"
                    "如需运行某策略，可指定 keyword（如 keyword='历史大底'）精准提取完整代码。"
                )
            return json.dumps(res_dict, ensure_ascii=False)
        except Exception as e:
            logger.error("get_user_strategies post-process error: %s", e)
            return result

    @mcp.tool()
    async def get_user_holdings() -> str:
        """
        获取当前用户持仓快照（实盘或模拟持仓记录）：
        包含持仓标的代码、持仓数量、成本价、当前市值与盈亏比例。
        【使用场景】当用户询问'我的持仓'、'我现在有哪些股票'时调用。
        """
        result = await _call("GET", "/api/v1/user/holdings")
        try:
            data = json.loads(result)
            if isinstance(data, list):
                return json.dumps({"status": "success", "total": len(data), "holdings": data}, ensure_ascii=False)
        except Exception:
            pass
        return result
