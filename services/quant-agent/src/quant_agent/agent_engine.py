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

def detect_intent_scope(
    query: str,
    page_context: str = "",
    is_admin: bool = False,
    agent_mode: str = "auto"
) -> str:
    """
    智能体领域与场景意图路由器 (Domain & Scenario Intent Router):
    物理隔离不同领域的工具集合，根除 LLM 跨界调用与偷看源码。
    
    :param query: 用户当前最新输入提问
    :param page_context: 前端路由或挂载工程等情境上下文
    :param is_admin: 用户是否具备超级管理员权限
    :param agent_mode: 请求指定的运行模式 ('auto' | 'quant' | 'devops' | 'all')
    :return: 判定的领域范围 ('quant' | 'devops' | 'all')
    """
    if not is_admin:
        return "quant"

    mode = (agent_mode or "auto").strip().lower()
    if mode in ("quant", "devops", "all"):
        return mode

    q = (query or "").lower()
    ctx = (page_context or "").lower()

    # 1. 明确的 DevOps / 运维 / 系统维护特征词
    devops_keywords = [
        "docker", "container", "容器", "重启", "restart", "reload",
        "shell", "bash", "终端", "命令行", "cmd",
        "git pull", "git push", "git status", "git commit", "git diff",
        "修改代码", "改下代码", "编辑文件", "修改文件", "写文件", "创建文件",
        "查看日志", "服务日志", "docker logs", "运行测试", "跑测试", "pytest",
        "系统状态", "服务器状态", "体检", "磁盘占用", "cpu使用率", "inspect_system",
        "编译", "deploy", "部署", "pnpm build", "uv run"
    ]
    has_devops_intent = any(kw in q for kw in devops_keywords)

    # 2. 明确的 Quant 投研 / 组合 / 回测 / 行情特征词
    quant_keywords = [
        "回测", "backtest", "自选", "组合", "portfolio", "watchlist",
        "策略", "strategy", "历史大底", "网格", "双均线", "dca", "定投",
        "行情", "k线", "kline", "股价", "成交额", "估值", "市盈率", "pe", "pb",
        "财报", "资产负债", "利润表", "现金流", "股东", "筹码", "龙虎榜",
        "板块", "选股", "国债", "无风险利率", "年化", "夏普", "最大回撤", "买入", "卖出"
    ]
    has_quant_intent = any(kw in q for kw in quant_keywords)

    # 3. 意图判定
    if has_devops_intent and not has_quant_intent:
        return "devops"
    
    if has_quant_intent and not has_devops_intent:
        return "quant"

    if has_devops_intent and has_quant_intent:
        return "all"

    # 若未包含明显特定关键词，但处于挂载工程代码工作区，倾向于 devops
    if "当前激活工程" in ctx or "物理工作目录" in ctx:
        return "devops"

    # 默认场景：量化主航道 (quant)
    return "quant"


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
            description="【核心策略库工具】获取当前用户个人策略库中保存的自定义量化策略清单与 Python 源码。\n"
                        "支持按策略名称关键词模糊查询（如 '历史大底'、'双均线'、'网格'）。\n"
                        "返回匹配策略的名称 (name)、目标标的 (symbol)、策略说明与可直接运行的 Python 源码 (code)。\n"
                        "【重要准则】：当用户提到'我的策略'、'跑我的历史大底策略'时，必须立即调用本工具获取代码，严禁去文件系统或项目源码库搜索！",
            category="quant"
        )
        async def get_user_strategies(keyword: Optional[str] = None, include_code: bool = False) -> str:
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
                        
                        # 智能紧凑投影：如果指定了关键词且匹配数 <= 2，或者只有 1 个策略，或者显式 include_code，返回完整 code
                        # 如果是无关键词概览且包含多个策略，仅返回元数据列表，避免多套完整源码塞爆模型上下文
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

                        res_dict = {
                            "status": "success",
                            "total": len(projected),
                            "strategies": projected
                        }
                        if not should_include_code and len(strategies) > 1:
                            res_dict["note"] = "为避免上下文过载，策略代码未全量展开。如需运行某策略，可指定 keyword（如 keyword='历史大底'）精准提取完整代码。"
                        return json.dumps(res_dict, ensure_ascii=False)
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

    def get_active_tool_registry(self, is_admin: bool = False, scope: str = "quant") -> ToolRegistry:
        """根据用户权限与领域范围 (scope) 动态合成激活的工具注册表"""
        if not is_admin:
            # 普通用户模式：严格仅暴露基础量化工具
            return self.tool_registry.filter_by_categories(["quant", "general"])

        if scope == "quant":
            # 专属量化模式：物理屏蔽所有 admin_devops / shell 工具，模型绝无法调用读源码/执行shell
            return self.tool_registry.filter_by_categories(["quant", "general"])
        elif scope == "devops":
            # 专属运维模式：仅暴露运维与 Shell 工具
            return self._admin_tool_registry.copy()
        else:
            # 全栈混合模式 (all)：量化与运维工具全量融合
            return self.tool_registry.copy().merge(self._admin_tool_registry)

    async def chat_stream(
        self,
        messages: List[Message],
        model: Optional[str] = None,
        provider: Optional[str] = None,
        system_prompt: Optional[str] = None,
        page_context: str = "",
        temperature: float = 0.2,
        is_admin: bool = False,
        agent_mode: str = "auto",
        execution_mode: str = "auto",
        sensitive_tools: Optional[List[str]] = None,
        approved_tool_calls: Optional[List[str]] = None,
        approved_tool_call: Optional[Dict[str, Any]] = None,
        thinking_level: str = "medium",
        max_steps: Optional[int] = None
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """流式调用封装：注入情境提示词并启动通用 ReAct 循环"""
        await self.initialize_tools()

        # 提取最新一条用户提问用于领域意图动态探测
        latest_user_query = ""
        for m in reversed(messages):
            if m.role == "user":
                latest_user_query = m.content or ""
                break

        resolved_scope = detect_intent_scope(
            query=latest_user_query,
            page_context=page_context,
            is_admin=is_admin,
            agent_mode=agent_mode
        )
        logger.info(
            "QuantAgent intent routing: is_admin=%s, agent_mode=%s, resolved_scope=%s, query_preview=%.40s",
            is_admin, agent_mode, resolved_scope, latest_user_query.replace("\n", " ")
        )

        final_system_prompt = system_prompt or build_system_prompt(
            page_context=page_context,
            is_admin=is_admin,
            thinking_level=thinking_level,
            scope=resolved_scope
        )
        active_registry = self.get_active_tool_registry(is_admin=is_admin, scope=resolved_scope)

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

