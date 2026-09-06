import json
import logging
import datetime
import httpx
from typing import List, Dict, Any, Optional, AsyncGenerator

from agent_core import BaseAgent, BaseTool, ToolRegistry, TokenGovernor, MCPHttpClient, tool
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

        # 多 MCP 客户端注册表：独立管理各分层分组（系统 stock、用户 user、未来扩展 custom）
        base_mcp_url = agent_config.MCP_GATEWAY_URL.rstrip('/')
        if base_mcp_url.endswith("/stock") or base_mcp_url.endswith("/system"):
            stock_url = base_mcp_url
            user_url = base_mcp_url.rsplit('/', 1)[0] + "/user"
        elif base_mcp_url.endswith("/user"):
            stock_url = base_mcp_url.rsplit('/', 1)[0] + "/stock"
            user_url = base_mcp_url
        else:
            stock_url = f"{base_mcp_url}/stock"
            user_url = f"{base_mcp_url}/user"

        self._mcp_clients: Dict[str, MCPHttpClient] = {
            "mcp-stock": MCPHttpClient(
                url=stock_url,
                server_name="mcp-stock",
                category="system",
                group="system",
                enabled=True,
            ),
            "mcp-user": MCPHttpClient(
                url=user_url,
                server_name="mcp-user",
                category="user",
                group="user",
                enabled=True,
                token_getter=lambda: current_user_token.get(),
            ),
        }

        # 超级管理员专属 DevOps 运维工具注册表
        self._admin_tool_registry = get_admin_tool_registry()

        # 注册内部沙箱量化工具（直接调用 quant-server，不经过网关）
        self._register_internal_quant_tools()


    def _register_internal_quant_tools(self):
        """
        挂载 quant-server 策略诊断与沙箱极速回测专属工具。
        注意：行情数据（get_realtime_quote 等）已在 mcp-stock 分组，
        用户数据（get_user_watchlists 等）已在 mcp-user 分组，由独立客户端动态发现。
        """

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


    async def initialize_stock_mcp(self, force_refresh: bool = False):
        """独立发现并挂载系统级行情中台 MCP 工具 (category='system')"""
        client = self._mcp_clients.get("mcp-stock")
        if not client:
            return []
        try:
            tools = await client.register_to(self.tool_registry)
            logger.info("QuantAgent: Discovered & registered %d system stock tools", len(tools))
            return tools
        except Exception as e:
            logger.error("QuantAgent: Failed to initialize system stock MCP: %s", e)
            return []

    async def initialize_user_mcp(self, force_refresh: bool = False):
        """独立发现并挂载用户专属数据 MCP 工具 (category='user')"""
        client = self._mcp_clients.get("mcp-user")
        if not client:
            return []
        try:
            tools = await client.register_to(self.tool_registry)
            logger.info("QuantAgent: Discovered & registered %d user data tools", len(tools))
            return tools
        except Exception as e:
            logger.error("QuantAgent: Failed to initialize user data MCP: %s", e)
            return []

    async def initialize_custom_mcps(self, force_refresh: bool = False):
        """加载配置中心中未来扩展添加的自定义/第三方 MCP 服务"""
        from quant_agent.settings import settings_manager
        cfg = settings_manager.get_config()
        loaded = []
        for s in cfg.mcp_servers:
            if s.name in ("mcp-stock", "mcp-user"):
                continue
            if not s.enabled:
                continue
            if s.type == "http" and s.url:
                if s.name not in self._mcp_clients:
                    self._mcp_clients[s.name] = MCPHttpClient(
                        url=s.url,
                        server_name=s.name,
                        category=s.category or "custom",
                        group=s.group or "custom",
                        enabled=s.enabled,
                    )
                try:
                    tools = await self._mcp_clients[s.name].register_to(self.tool_registry)
                    loaded.extend(tools)
                    logger.info("QuantAgent: Loaded %d tools from custom MCP '%s'", len(tools), s.name)
                except Exception as e:
                    logger.error("QuantAgent: Failed to load custom MCP '%s': %s", s.name, e)
        return loaded

    async def initialize_tools(self, force_refresh: bool = False):
        """动态分步编排发现并挂载所有分组的 MCP 工具"""
        if self._tools_initialized and not force_refresh:
            return

        # 1. 加载系统行情 MCP
        await self.initialize_stock_mcp(force_refresh=force_refresh)

        # 2. 加载用户专属数据 MCP
        await self.initialize_user_mcp(force_refresh=force_refresh)

        # 3. 加载扩展 MCP
        await self.initialize_custom_mcps(force_refresh=force_refresh)

        self._tools_initialized = True
        logger.info(
            "QuantAgent successfully initialized all tool groups (total active: %d)",
            len(self.tool_registry.list_tools())
        )

    def get_active_tool_registry(self, is_admin: bool = False, scope: str = "quant") -> ToolRegistry:
        """
        根据用户权限与领域范围 (scope) 动态合成激活的工具注册表。
        已根据 settings 中各 MCP Server 的 enabled 状态动态过滤！
        """
        from quant_agent.settings import settings_manager
        cfg = settings_manager.get_config()

        all_disabled_tools = set(getattr(cfg, "disabled_tools", []) or [])

        # 动态统计当前启用的工具分类
        active_categories = ["quant", "general"]
        for s in cfg.mcp_servers:
            if s.enabled:
                if s.name == "mcp-stock":
                    active_categories.extend(["system", "stock", "quant"])
                elif s.name == "mcp-user":
                    active_categories.append("user")
                elif s.category:
                    active_categories.append(s.category)
                if getattr(s, "disabled_tools", None):
                    all_disabled_tools.update(s.disabled_tools)

        active_categories = list(set(active_categories))

        if not is_admin:
            # 普通用户模式：严格暴露当前启用的基础量化、用户自选与通用扩展工具，并排除被禁用的单个工具
            reg = self.tool_registry.filter_by_categories(active_categories)
            if all_disabled_tools:
                reg = reg.exclude_tools(list(all_disabled_tools))
            return reg

        # 超管系统级运维工具总开关检查
        admin_tools_enabled = getattr(cfg, "admin_tools_enabled", True)

        if scope == "quant" or not admin_tools_enabled:
            # 专属量化模式或超管关闭了系统级运维工具：物理屏蔽所有 admin_devops / shell 工具
            reg = self.tool_registry.filter_by_categories(active_categories)
            if all_disabled_tools:
                reg = reg.exclude_tools(list(all_disabled_tools))
            return reg
        elif scope == "devops":
            # 专属运维模式：仅暴露运维与 Shell 工具
            reg = self._admin_tool_registry.copy()
            if all_disabled_tools:
                reg = reg.exclude_tools(list(all_disabled_tools))
            return reg
        else:
            # 全栈混合模式 (all)：量化与运维工具全量融合
            base_reg = self.tool_registry.filter_by_categories(active_categories)
            merged = base_reg.merge(self._admin_tool_registry)
            if all_disabled_tools:
                merged = merged.exclude_tools(list(all_disabled_tools))
            return merged

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

