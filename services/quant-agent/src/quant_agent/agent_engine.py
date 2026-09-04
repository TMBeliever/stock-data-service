import json
import logging
from typing import List, Dict, Any, Optional, AsyncGenerator
from ai_core.orchestrator import ai_orchestrator
from ai_core.models import Message, ToolCall, AIResponse, ToolDefinition

from quant_agent.config import agent_config
from quant_agent.mcp_manager import mcp_manager
from quant_agent.prompts import build_system_prompt

logger = logging.getLogger(__name__)

class QuantAgentEngine:
    """
    金融量化智能体决策引擎：
    驱动 ReAct 循环 (Think -> Action -> Observation)，自动挂载 MCP 金融数据与回测工具，
    并向多端客户端推送结构化的 SSE 事件流。
    """
    def __init__(self):
        self.mcp = mcp_manager

    async def chat_stream(
        self,
        messages: List[Message],
        model: Optional[str] = None,
        provider: Optional[str] = None,
        system_prompt: Optional[str] = None,
        page_context: str = "",
        temperature: float = 0.2
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        流式 ReAct 决策生成器：
        逐事件推送 tool_call (工具调用)、tool_result (数据返回)、message (正文增量分片)、done (完成)。
        """
        # 1. 组装情境感知的系统设定
        final_sys_prompt = system_prompt or build_system_prompt(page_context)
        
        # 确保系统提示词在消息首位
        active_messages: List[Message] = []
        has_system = False
        for m in messages:
            if m.role == "system":
                active_messages.append(Message.system(final_sys_prompt))
                has_system = True
            else:
                active_messages.append(m)
        if not has_system:
            active_messages.insert(0, Message.system(final_sys_prompt))

        # 2. 动态拉取所有挂载的 MCP 工具
        tools: List[ToolDefinition] = await self.mcp.list_tools()
        model_name = model or agent_config.DEFAULT_MODEL
        provider_type = provider or agent_config.DEFAULT_PROVIDER

        max_steps = agent_config.MAX_AGENT_STEPS

        # 3. 智能体 ReAct 认知循环
        for step in range(max_steps):
            logger.info("Agent Step %d/%d with %d tools and %d messages", step + 1, max_steps, len(tools), len(active_messages))
            
            try:
                # 针对第一步决策，先进行一次工具决策研判
                response: AIResponse = await ai_orchestrator.generate(
                    messages=active_messages,
                    tools=tools,
                    model=model_name,
                    provider_type=provider_type,
                    temperature=temperature
                )
            except Exception as e:
                logger.error("AI Generation error at step %d: %s", step + 1, str(e))
                yield {
                    "event": "error",
                    "data": json.dumps({"error": f"Model gateway error: {str(e)}"}, ensure_ascii=False)
                }
                return

            # 判断是否有工具调用
            if response.tool_calls and len(response.tool_calls) > 0:
                # 记录 Assistant 的工具调用消息
                active_messages.append(Message.assistant(
                    content=response.content or "",
                    tool_calls=response.tool_calls
                ))

                for tc in response.tool_calls:
                    # 推送 tool_call 事件到客户端
                    yield {
                        "event": "tool_call",
                        "data": json.dumps({
                            "id": tc.id,
                            "name": tc.name,
                            "arguments": tc.arguments,
                            "step": step + 1
                        }, ensure_ascii=False)
                    }

                    # 执行工具
                    logger.info("Executing tool '%s' with args %s", tc.name, tc.arguments)
                    tool_output = await self.mcp.call_tool(tc.name, tc.arguments)

                    # 推送 tool_result 事件到客户端 (提供摘要便于界面快速渲染)
                    yield {
                        "event": "tool_result",
                        "data": json.dumps({
                            "id": tc.id,
                            "name": tc.name,
                            "output_preview": tool_output[:300] if len(tool_output) > 300 else tool_output,
                            "step": step + 1
                        }, ensure_ascii=False)
                    }

                    # 将 Observation (工具执行结果) 加入上下文
                    active_messages.append(Message.tool_result(
                        tool_call_id=tc.id,
                        content=tool_output,
                        name=tc.name
                    ))

                # 继续下一轮循环，模型会基于工具结果进行解答
                continue
            else:
                # 模型无需（或已结束）调用工具，直接输出最终回答
                final_text = response.content or ""
                # 分块平滑流式推送给客户端
                chunk_size = 12
                for i in range(0, len(final_text), chunk_size):
                    chunk_str = final_text[i:i + chunk_size]
                    yield {
                        "event": "message",
                        "data": json.dumps({
                            "delta": chunk_str,
                            "role": "assistant"
                        }, ensure_ascii=False)
                    }
                break

        # 结束事件
        yield {
            "event": "done",
            "data": json.dumps({"status": "finished"}, ensure_ascii=False)
        }

agent_engine = QuantAgentEngine()
