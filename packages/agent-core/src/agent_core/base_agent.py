import json
import logging
import httpx
from typing import AsyncGenerator, Dict, Any, List, Optional
from ai_core.models import Message, ToolCall, ToolDefinition
from agent_core.tool import ToolRegistry
from agent_core.token_governor import TokenGovernor

logger = logging.getLogger(__name__)

class BaseAgent:
    """
    通用智能体运行基类 (Universal Agent Harness):
    封装 ReAct 循环核心、工具分发、Token 截断治理与多端流式事件协议
    """
    def __init__(
        self,
        name: str = "UniversalAgent",
        system_prompt: str = "你是一个高效、严谨且具备自主工具调用能力的通用 AI 助手。",
        tool_registry: Optional[ToolRegistry] = None,
        token_governor: Optional[TokenGovernor] = None,
        ai_core_url: str = "http://localhost:8070",
        max_steps: int = 8
    ):
        self.name = name
        self.system_prompt = system_prompt
        self.tool_registry = tool_registry or ToolRegistry()
        self.token_governor = token_governor or TokenGovernor()
        self.ai_core_url = ai_core_url.rstrip("/")
        self.max_steps = max_steps

    async def _call_llm_generate(
        self,
        messages: List[Message],
        tools: List[ToolDefinition],
        model: Optional[str] = None,
        provider: Optional[str] = None,
        temperature: Optional[float] = 0.2
    ) -> Dict[str, Any]:
        """向底层模型网关 (ai-core) 发起单次结构化生成请求"""
        url = f"{self.ai_core_url}/api/v1/ai/generate"
        payload = {
            "messages": [m.model_dump(exclude_none=True) for m in messages],
            "tools": [t.model_dump() for t in tools] if tools else None,
            "model": model,
            "provider": provider,
            "temperature": temperature
        }

        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code != 200:
                raise RuntimeError(f"AI Core error ({resp.status_code}): {resp.text}")
            return resp.json()

    async def stream_chat(
        self,
        prompt: Optional[str] = None,
        messages: Optional[List[Message]] = None,
        model: Optional[str] = None,
        provider: Optional[str] = None,
        temperature: Optional[float] = 0.2,
        system_prompt_override: Optional[str] = None,
        tool_category: Optional[str] = None
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        通用 ReAct 流式交互调度器：
        自主循环调用模型与工具，并通过生成器 yield SSE 规范事件
        """
        active_sys_prompt = system_prompt_override or self.system_prompt

        # 1. 组装初始对话消息 (保持静态 Prompt Cache 友好排布)
        history: List[Message] = []
        history.append(Message.system(active_sys_prompt))

        if messages and len(messages) > 0:
            for m in messages:
                if m.role != "system":
                    history.append(m)
        elif prompt:
            history.append(Message.user(prompt))

        # 2. 准备工具定义列表并稳定排序 (Prompt Cache 命中优化)
        raw_tools = self.tool_registry.to_definitions(category=tool_category)
        tools = self.token_governor.sort_tools_for_caching(raw_tools)

        logger.info(
            "Starting agent '%s' chat loop with %d tools mounted (max_steps=%d)",
            self.name, len(tools), self.max_steps
        )

        step = 0
        while step < self.max_steps:
            step += 1

            # 3. 检查是否需要触发 Token Compaction
            if self.token_governor.needs_compaction(history, step):
                history = self.token_governor.compact_history(history)

            # 4. 调用模型生成
            try:
                ai_resp_data = await self._call_llm_generate(
                    messages=history,
                    tools=tools,
                    model=model,
                    provider=provider,
                    temperature=temperature
                )
            except Exception as e:
                err_msg = f"智能体模型推理调度异常: {str(e)}"
                logger.error(err_msg)
                yield {
                    "event": "message",
                    "data": json.dumps({"delta": f"\n\n> ⚠️ **执行异常**: {err_msg}", "role": "assistant"}, ensure_ascii=False)
                }
                yield {"event": "done", "data": json.dumps({"status": "error"})}
                return

            resp_content = ai_resp_data.get("content") or ""
            raw_tool_calls = ai_resp_data.get("tool_calls") or []

            # 5. 分支 A: 模型发起了工具调用 (Tool Calling)
            if raw_tool_calls and len(raw_tool_calls) > 0:
                parsed_calls = [
                    ToolCall(
                        id=c.get("id", f"call_{step}"),
                        name=c.get("name") or (c.get("function") or {}).get("name", ""),
                        arguments=c.get("arguments") or (c.get("function") or {}).get("arguments", {})
                    )
                    for c in raw_tool_calls
                ]

                # 记录 assistant 发起的 tool_calls
                history.append(Message.assistant(content=resp_content, tool_calls=parsed_calls))

                for tc in parsed_calls:
                    # 5.1 推送 tool_call 开始事件
                    yield {
                        "event": "tool_call",
                        "data": json.dumps({
                            "id": tc.id,
                            "name": tc.name,
                            "arguments": tc.arguments,
                            "step": step
                        }, ensure_ascii=False)
                    }

                    # 5.2 执行工具
                    try:
                        raw_result = await self.tool_registry.execute(tc.name, tc.arguments)
                    except Exception as e:
                        raw_result = f"Error executing tool '{tc.name}': {str(e)}"

                    # 5.3 通过 TokenGovernor 进行 Observation 观察截断保护
                    truncated_result = self.token_governor.truncate_observation(raw_result)

                    # 5.4 推送 tool_result 完成事件
                    preview = truncated_result[:300] if len(truncated_result) > 300 else truncated_result
                    yield {
                        "event": "tool_result",
                        "data": json.dumps({
                            "id": tc.id,
                            "name": tc.name,
                            "output_preview": preview,
                            "step": step
                        }, ensure_ascii=False)
                    }

                    # 5.5 结果作为 tool 消息压入历史
                    history.append(Message.tool_result(tool_call_id=tc.id, content=truncated_result, name=tc.name))

                # 继续下一轮 ReAct 思考与综合
                continue

            # 6. 分支 B: 模型未调用工具，输出了最终回答
            if resp_content:
                # 分段逐块平滑推送最终文本
                chunk_size = 12
                for i in range(0, len(resp_content), chunk_size):
                    delta = resp_content[i:i + chunk_size]
                    yield {
                        "event": "message",
                        "data": json.dumps({"delta": delta, "role": "assistant"}, ensure_ascii=False)
                    }

            yield {"event": "done", "data": json.dumps({"status": "finished"})}
            return

        # 达到最大步数兜底处理
        yield {
            "event": "message",
            "data": json.dumps({
                "delta": f"\n\n> ⚠️ **步数限制**: 已达到最大工具执行深度 ({self.max_steps} 步)，任务强制终止。",
                "role": "assistant"
            }, ensure_ascii=False)
        }
        yield {"event": "done", "data": json.dumps({"status": "finished"})}
