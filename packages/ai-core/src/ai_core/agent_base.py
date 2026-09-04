import json
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Callable, Awaitable
from pydantic import BaseModel, Field
from ai_core.base import BaseAIProvider
from ai_core.models import Message, ToolDefinition, ToolCall, AIResponse

class AgentStep(BaseModel):
    """智能体单步执行结果"""
    step_number: int
    thought: str = ""
    tool_calls: Optional[List[ToolCall]] = None
    tool_results: Optional[List[Dict[str, Any]]] = None
    final_answer: Optional[str] = None
    is_finished: bool = False

class AgentMemory:
    """智能体对话与执行上下文记忆库"""
    def __init__(self, system_prompt: Optional[str] = None):
        self.messages: List[Message] = []
        if system_prompt:
            self.messages.append(Message.system(system_prompt))

    def add_user_message(self, content: str):
        self.messages.append(Message.user(content))

    def add_assistant_message(self, content: Optional[str] = None, tool_calls: Optional[List[ToolCall]] = None):
        self.messages.append(Message.assistant(content=content, tool_calls=tool_calls))

    def add_tool_result(self, tool_call_id: str, result: str, name: Optional[str] = None):
        self.messages.append(Message.tool_result(tool_call_id=tool_call_id, content=result, name=name))

    def clear(self, keep_system: bool = True):
        if keep_system and self.messages and self.messages[0].role == "system":
            self.messages = [self.messages[0]]
        else:
            self.messages = []

class BaseAgent(ABC):
    """
    通用智能体 (Agent) 抽象状态机基类：
    零业务绑定，封装 ReAct (Thought -> Action -> Observation) 决策与工具循环骨架。
    具体领域的 Agent (如 QuantStrategyAgent) 继承该基类并挂载专业工具即可。
    """
    def __init__(
        self,
        provider: BaseAIProvider,
        system_prompt: Optional[str] = None,
        max_steps: int = 10
    ):
        self.provider = provider
        self.max_steps = max_steps
        self.memory = AgentMemory(system_prompt=system_prompt)
        self._tools: Dict[str, tuple[ToolDefinition, Callable[..., Any]]] = {}

    def register_tool(
        self,
        definition: ToolDefinition,
        func: Callable[..., Any]
    ):
        """挂载可调用工具函数"""
        self._tools[definition.name] = (definition, func)

    def get_tool_definitions(self) -> List[ToolDefinition]:
        return [t[0] for t in self._tools.values()]

    async def execute_tool(self, tool_call: ToolCall) -> str:
        """分发并执行具体的挂载工具"""
        if tool_call.name not in self._tools:
            return f"Error: Tool '{tool_call.name}' not found."

        _, func = self._tools[tool_call.name]
        try:
            import inspect
            if inspect.iscoroutinefunction(func):
                res = await func(**tool_call.arguments)
            else:
                res = func(**tool_call.arguments)

            if isinstance(res, (dict, list)):
                return json.dumps(res, ensure_ascii=False)
            return str(res)
        except Exception as e:
            return f"Tool execution error: {str(e)}"

    async def step(self, step_number: int) -> AgentStep:
        """执行单次认知循环决策 (Think & Act)"""
        tools_def = self.get_tool_definitions() if self._tools else None
        response: AIResponse = await self.provider.generate(
            messages=self.memory.messages,
            tools=tools_def
        )

        # 记录 AI 思考与输出
        self.memory.add_assistant_message(
            content=response.content,
            tool_calls=response.tool_calls
        )

        # 若无工具调用，说明已得出最终回答
        if not response.tool_calls:
            return AgentStep(
                step_number=step_number,
                thought=response.content,
                final_answer=response.content,
                is_finished=True
            )

        # 若存在工具调用，逐一执行并回传 Observation
        results = []
        for tc in response.tool_calls:
            obs = await self.execute_tool(tc)
            self.memory.add_tool_result(tool_call_id=tc.id, result=obs, name=tc.name)
            results.append({"tool_call_id": tc.id, "name": tc.name, "result": obs})

        return AgentStep(
            step_number=step_number,
            thought=response.content,
            tool_calls=response.tool_calls,
            tool_results=results,
            is_finished=False
        )

    async def run(self, goal: str) -> str:
        """启动自主智能体循环直至完成目标或达到最大步数"""
        self.memory.add_user_message(goal)

        for i in range(1, self.max_steps + 1):
            step_res = await self.step(step_number=i)
            if step_res.is_finished and step_res.final_answer is not None:
                return step_res.final_answer

        return "Agent reached maximum step limit without concluding."
