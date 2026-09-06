import json
import logging
import datetime
import httpx
from typing import List, Dict, Any, Optional, AsyncGenerator

from agent_core import BaseAgent, BaseTool, ToolRegistry, TokenGovernor, MCPClient, tool
from ai_core.models import Message, ToolDefinition

from quant_agent.config import agent_config
from quant_agent.prompts import build_system_prompt, QUANT_COPILOT_SYSTEM_PROMPT
from quant_agent.admin_tools import get_admin_tool_registry
from quant_agent.auth import current_user_token

logger = logging.getLogger(__name__)

class QuantAgent(BaseAgent):
    """
    量化投研与策略工程智能体 (Quant Copilot):
    继承自通用智能体底座 BaseAgent，特化挂载 MCP 金融行情工具、本地量化沙箱工具，以及超级管理员专属运维控制工具。
    """
    def __init__(self):
        token_governor = TokenGovernor(
            max_observation_chars=4000,
            max_observation_lines=120,
            compaction_step_threshold=16,
            max_history_tokens_estimate=32000
        )

        super().__init__(
            name="QuantCopilotAgent",
            system_prompt=QUANT_COPILOT_SYSTEM_PROMPT,
            tool_registry=ToolRegistry(),
            token_governor=token_governor,
            ai_core_url=agent_config.AI_CORE_URL,
            api_key=agent_config.AI_CORE_API_KEY,
            max_steps=agent_config.MAX_AGENT_STEPS
        )

        self._tools_initialized = False
        self._mcp_client = MCPClient(
            command="uv",
            args=["run", "python", "mcp_server.py"],
            cwd=agent_config.STOCK_DATA_DIR,
            server_name="stock-data-mcp",
            category="quant"
        )

        # 超级管理员专属 DevOps 运维工具注册表
        self._admin_tool_registry = get_admin_tool_registry()

        # 注册内部沙箱量化工具
        self._register_internal_quant_tools()

    def _register_internal_quant_tools(self):
        """挂载 quant-server 策略诊断与沙箱极速回测专属工具"""

        @tool(
            name="validate_strategy_code",
            description="校验 Python 量化策略源码的语法、BaseStrategy 规范与导入安全限制，返回诊断意见。",
            category="quant"
        )
        async def validate_strategy_code(code: str) -> str:
            """
            :param code: 待诊断的 Python 策略源代码完整文本
            """
            url = f"{agent_config.QUANT_SERVER_URL}/api/v1/sandbox/validate"
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.post(url, json={"code": code})
                    return json.dumps(resp.json(), ensure_ascii=False)
            except Exception as e:
                return json.dumps({"is_valid": False, "error": f"Sandbox service unavailable: {str(e)}"}, ensure_ascii=False)

        @tool(
            name="get_user_watchlists",
            description="【核心投研数据工具】获取当前用户在平台保存的所有自选股票池与投资组合列表 (User Watchlists)。\n"
                        "返回各组合名称（如 '稳健组合'、'高股息资产'、'核心资产'）、包含的标的代码列表 (symbols 如 ['510300.SH.ETF', '510500.SH.ETF']) 以及创建时间。\n"
                        "【重要准则】：当用户提及'我的组合'、'我的自选'、'稳健组合'或要求对特定组合进行回测/分析时，必须立即且优先调用本工具获取真实标的代码，绝对禁止翻看项目源码！",
            category="quant"
        )
        async def get_user_watchlists() -> str:
            token = current_user_token.get()
            headers = {"X-Internal-Service": "quant-agent"}
            if token:
                headers["Authorization"] = token if token.startswith("Bearer ") else f"Bearer {token}"
            url = f"{agent_config.COMMON_SERVER_URL}/api/v1/user/watchlists"
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(url, headers=headers)
                    if resp.status_code == 200:
                        data = resp.json()
                        return json.dumps({
                            "status": "success",
                            "total": len(data),
                            "watchlists": data
                        }, ensure_ascii=False)
                    return json.dumps({"status": "failed", "code": resp.status_code, "detail": resp.text}, ensure_ascii=False)
            except Exception as e:
                return json.dumps({"status": "error", "error": f"用户组合服务不可用: {str(e)}"}, ensure_ascii=False)

        @tool(
            name="get_user_strategies",
            description="【核心策略库工具】获取当前用户个人策略库中保存的自定义量化策略清单与完整 Python 源码。\n"
                        "支持按策略名称关键词模糊查询（如 '历史大底'、'双均线'、'网格'）。\n"
                        "返回匹配策略的名称 (name)、目标标的 (symbol)、策略说明与可直接运行的 Python 源码 (code)。\n"
                        "【重要准则】：当用户提到'我的策略'、'跑我的历史大底策略'时，必须立即调用本工具获取代码，严禁去文件系统或项目源码库搜索！",
            category="quant"
        )
        async def get_user_strategies(keyword: Optional[str] = None) -> str:
            token = current_user_token.get()
            headers = {"X-Internal-Service": "quant-agent"}
            if token:
                headers["Authorization"] = token if token.startswith("Bearer ") else f"Bearer {token}"
            url = f"{agent_config.COMMON_SERVER_URL}/api/v1/user/strategies"
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(url, headers=headers)
                    if resp.status_code == 200:
                        strategies = resp.json()
                        if keyword and str(keyword).strip():
                            kw = str(keyword).strip().lower()
                            strategies = [
                                s for s in strategies
                                if kw in s.get("name", "").lower() or kw in (s.get("description") or "").lower()
                            ]
                        return json.dumps({
                            "status": "success",
                            "total": len(strategies),
                            "strategies": [
                                {
                                    "id": s.get("id"),
                                    "name": s.get("name"),
                                    "symbol": s.get("symbol"),
                                    "description": s.get("description"),
                                    "code": s.get("code")
                                }
                                for s in strategies
                            ]
                        }, ensure_ascii=False)
                    return json.dumps({"status": "failed", "code": resp.status_code, "detail": resp.text}, ensure_ascii=False)
            except Exception as e:
                return json.dumps({"status": "error", "error": f"用户策略库服务不可用: {str(e)}"}, ensure_ascii=False)

        @tool(
            name="run_backtest_fast",
            description="在 quant-server 沙箱中极速运行量化回测，原生支持单标的或多标的自选组合(symbols)，返回总收益率、年化夏普比率、最大回撤等核心 KPI 结果。\n"
                        "参数说明:\n"
                        "- code: Python 策略源代码\n"
                        "- symbol: 单个标的代码 (如 '510300.SH.ETF')\n"
                        "- symbols: 多标的代码列表 (如 ['510880.SH.ETF', '513100.SH.ETF'])\n"
                        "- start: 起始日期 YYYY-MM-DD (如 '2020-01-01')\n"
                        "- end: 截止日期 YYYY-MM-DD (留空默认最新交易日)\n"
                        "- initial_cash: 初始资金 (默认 100000.0)",
            category="quant"
        )
        async def run_backtest_fast(
            code: str,
            symbol: Optional[str] = None,
            symbols: Optional[List[str]] = None,
            start: str = "2020-01-01",
            end: Optional[str] = None,
            initial_cash: float = 100000.0
        ) -> str:
            """
            :param code: Python 策略源代码
            :param symbol: 标的代码 (如 510300, 600519)
            :param symbols: 标的代码列表 (多标的组合回测)
            :param start: 起始日期 YYYY-MM-DD
            :param end: 截止日期 YYYY-MM-DD
            :param initial_cash: 初始资金 (默认 100000.0)
            """
            target_symbols = symbols if (symbols and len(symbols) > 0) else ([symbol] if symbol else ["510300.SH.ETF"])
            url = f"{agent_config.QUANT_SERVER_URL}/api/v1/backtest/run-custom"
            payload = {
                "code": code,
                "symbols": target_symbols,
                "symbol": target_symbols[0] if target_symbols else "510300.SH.ETF",
                "start": start,
                "end": end or datetime.date.today().strftime("%Y-%m-%d"),
                "initial_cash": float(initial_cash),
            }
            try:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    resp = await client.post(url, json=payload)
                    if resp.status_code == 200:
                        data = resp.json()
                        summary = data.get("summary", {})
                        return json.dumps({
                            "status": "success",
                            "target_symbols": target_symbols,
                            "period": f"{payload['start']} ~ {payload['end']}",
                            "total_return": summary.get("total_return"),
                            "annualized_return": summary.get("annualized_return"),
                            "sharpe_ratio": summary.get("sharpe_ratio"),
                            "max_drawdown": summary.get("max_drawdown"),
                            "win_rate": summary.get("win_rate"),
                            "total_trades": summary.get("total_trades"),
                            "trades_count": len(data.get("trades", [])),
                        }, ensure_ascii=False)
                    return json.dumps({"status": "failed", "detail": resp.text}, ensure_ascii=False)
            except Exception as e:
                return json.dumps({"status": "error", "error": f"Backtest engine unavailable: {str(e)}"}, ensure_ascii=False)

        self.tool_registry.register(validate_strategy_code)
        self.tool_registry.register(run_backtest_fast)
        self.tool_registry.register(get_user_watchlists)
        self.tool_registry.register(get_user_strategies)

    async def initialize_tools(self, force_refresh: bool = False):
        """动态发现并挂载 stock-data MCP 工具"""
        if self._tools_initialized and not force_refresh:
            return

        try:
            await self._mcp_client.register_to(self.tool_registry)
            self._tools_initialized = True
            logger.info("QuantAgent successfully initialized %d tools", len(self.tool_registry.list_tools()))
        except Exception as e:
            logger.error("Failed to initialize MCP tools for QuantAgent: %s", e)

    def get_active_tool_registry(self, is_admin: bool = False) -> ToolRegistry:
        """根据用户权限动态合成激活的工具注册表"""
        if is_admin:
            # 管理员模式：融合基础量化工具 + 超管 DevOps 运维工具
            return self.tool_registry.copy().merge(self._admin_tool_registry)
        # 普通用户模式：严格仅暴露基础量化工具
        return self.tool_registry

    async def chat_stream(
        self,
        messages: List[Message],
        model: Optional[str] = None,
        provider: Optional[str] = None,
        system_prompt: Optional[str] = None,
        page_context: str = "",
        temperature: float = 0.2,
        is_admin: bool = False,
        execution_mode: str = "auto",
        sensitive_tools: Optional[List[str]] = None,
        approved_tool_calls: Optional[List[str]] = None,
        approved_tool_call: Optional[Dict[str, Any]] = None,
        thinking_level: str = "medium",
        max_steps: Optional[int] = None
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """流式调用封装：注入情境提示词并启动通用 ReAct 循环"""
        await self.initialize_tools()

        final_system_prompt = system_prompt or build_system_prompt(page_context, is_admin=is_admin, thinking_level=thinking_level)
        active_registry = self.get_active_tool_registry(is_admin=is_admin)

        async for event in self.stream_chat(
            messages=messages,
            model=model,
            provider=provider,
            temperature=temperature,
            system_prompt_override=final_system_prompt,
            tool_registry_override=active_registry,
            execution_mode=execution_mode,
            sensitive_tools=sensitive_tools,
            approved_tool_calls=approved_tool_calls,
            approved_tool_call=approved_tool_call,
            thinking_level=thinking_level,
            max_steps_override=max_steps
        ):
            yield event

quant_agent = QuantAgent()

