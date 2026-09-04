import pytest
from typing import List, Optional, AsyncGenerator
from ai_core.base import BaseAIProvider
from ai_core.models import Message, AIResponse, StreamChunk, ToolDefinition, ToolCall
from ai_core.agent_base import BaseAgent

class MockAgentProvider(BaseAIProvider):
    """用于测试 Agent 决策循环的模拟提供者"""
    def __init__(self):
        self.call_count = 0

    @property
    def provider_type(self) -> str:
        return "key"

    async def generate(
        self,
        messages: List[Message],
        tools: Optional[List[ToolDefinition]] = None,
        **kwargs
    ) -> AIResponse:
        self.call_count += 1
        if self.call_count == 1:
            # 步骤 1：模型决定调用工具计算夏普比率
            return AIResponse(
                content="I need to calculate the sharpe ratio first.",
                model="mock-model",
                provider_type="key",
                tool_calls=[
                    ToolCall(
                        id="call_calc_1",
                        name="calc_sharpe",
                        arguments={"annual_return": 0.15, "volatility": 0.10}
                    )
                ]
            )
        else:
            # 步骤 2：模型收到观察结果，输出最终报告
            return AIResponse(
                content="The strategy Sharpe ratio is 1.5, which is solid.",
                model="mock-model",
                provider_type="key"
            )

    async def generate_stream(
        self,
        messages: List[Message],
        tools: Optional[List[ToolDefinition]] = None,
        **kwargs
    ) -> AsyncGenerator[StreamChunk, None]:
        yield StreamChunk(delta="mock stream")

class QuantReviewAgent(BaseAgent):
    """测试用例：继承 BaseAgent 扩展专业量化能力"""
    pass

@pytest.mark.asyncio
async def test_agent_tool_execution_loop():
    mock_provider = MockAgentProvider()
    agent = QuantReviewAgent(
        provider=mock_provider,
        system_prompt="You are a quant review agent.",
        max_steps=5
    )

    # 注册量化工具
    def calc_sharpe(annual_return: float, volatility: float) -> float:
        return round(annual_return / volatility, 2)

    agent.register_tool(
        definition=ToolDefinition(
            name="calc_sharpe",
            description="Calculate Sharpe Ratio",
            parameters={
                "type": "object",
                "properties": {
                    "annual_return": {"type": "number"},
                    "volatility": {"type": "number"}
                },
                "required": ["annual_return", "volatility"]
            }
        ),
        func=calc_sharpe
    )

    final_result = await agent.run("Evaluate dividend strategy performance.")
    assert "The strategy Sharpe ratio is 1.5" in final_result
    assert mock_provider.call_count == 2
    # 验证记忆库中完整保存了提问、思考、工具调用、工具返回值与最终回答
    assert len(agent.memory.messages) == 5
    assert agent.memory.messages[0].role == "system"
    assert agent.memory.messages[1].role == "user"
    assert agent.memory.messages[2].role == "assistant"
    assert agent.memory.messages[3].role == "tool"
    assert agent.memory.messages[3].content == "1.5"
    assert agent.memory.messages[4].role == "assistant"
