import pytest
import asyncio
from agent_core.tool import tool, ToolRegistry, BaseTool
from agent_core.token_governor import TokenGovernor
from agent_core.builtin_tools.filesystem import read_file, write_file, list_dir
from agent_core.base_agent import BaseAgent
from ai_core.models import Message

def test_tool_decorator_and_registry():
    registry = ToolRegistry()

    @tool(name="mock_add", description="计算两数之和", category="math")
    def mock_add(a: int, b: int = 10) -> int:
        """两数相加"""
        return a + b

    registry.register(mock_add)
    t = registry.get_tool("mock_add")
    assert t is not None
    assert t.name == "mock_add"
    assert t.category == "math"
    assert "a" in t.parameters["properties"]
    assert "b" in t.parameters["properties"]
    assert t.parameters["properties"]["a"]["type"] == "integer"
    assert t.parameters["properties"]["b"]["default"] == 10

    defs = registry.to_definitions(category="math")
    assert len(defs) == 1
    assert defs[0].name == "mock_add"

@pytest.mark.asyncio
async def test_tool_execution():
    registry = ToolRegistry()

    @tool(name="async_multiply", description="异步乘法")
    async def async_multiply(x: int, y: int) -> int:
        await asyncio.sleep(0.01)
        return x * y

    registry.register(async_multiply)
    res = await registry.execute("async_multiply", {"x": 6, "y": 7})
    assert res == 42

def test_token_governor_truncation():
    governor = TokenGovernor(max_observation_chars=100, max_observation_lines=5)
    
    # 正常文本未超标
    short_text = "Hello world"
    assert governor.truncate_observation(short_text) == "Hello world"

    # 超长文本截断测试
    long_text = "Line\n" * 20 + "A" * 300
    truncated = governor.truncate_observation(long_text)
    assert len(truncated) > 0
    assert "Output truncated by TokenGovernor" in truncated

def test_token_governor_compaction():
    governor = TokenGovernor(compaction_step_threshold=3)
    msgs = [
        Message.system("System prompt"),
        Message.user("User prompt 1"),
        Message.assistant(content="Step 1 thinking"),
        Message.tool_result(tool_call_id="c1", content="res 1", name="tool1"),
        Message.assistant(content="Step 2 thinking"),
        Message.tool_result(tool_call_id="c2", content="res 2", name="tool2"),
        Message.assistant(content="Step 3 thinking"),
        Message.user("Recent message")
    ]

    assert governor.needs_compaction(msgs, current_step=3) is True
    compacted = governor.compact_history(msgs)
    assert len(compacted) < len(msgs)
    assert any("Token Compaction" in (m.content or "") for m in compacted)

def test_filesystem_tools(tmp_path):
    test_file = tmp_path / "sample.txt"
    write_res = write_file(str(test_file), "Line 1\nLine 2\nLine 3\n")
    assert "Success" in write_res

    read_res = read_file(str(test_file), offset=1, limit=2)
    assert "Line 1" in read_res
    assert "Line 2" in read_res

    list_res = list_dir(str(tmp_path))
    assert "sample.txt" in list_res

@pytest.mark.asyncio
async def test_base_agent_react_loop():
    registry = ToolRegistry()

    @tool(name="calc_tax", description="计算税率")
    def calc_tax(income: float) -> float:
        return income * 0.2

    registry.register(calc_tax)
    agent = BaseAgent(name="TestAgent", tool_registry=registry)

    # 模拟两次 LLM 响应：第一次触发 tool_call，第二次输出最终结论
    call_count = 0
    async def mock_llm_generate(messages, tools, model=None, provider=None, temperature=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_mock_1",
                        "name": "calc_tax",
                        "arguments": {"income": 1000.0}
                    }
                ]
            }
        else:
            return {
                "content": "计算完成，税费为 200 元。",
                "tool_calls": []
            }

    agent._call_llm_generate = mock_llm_generate

    events = []
    async for event in agent.stream_chat(prompt="帮我算一下 1000 元的税"):
        events.append(event)

    event_names = [e["event"] for e in events]
    assert "tool_call" in event_names
    assert "tool_result" in event_names
    assert "message" in event_names
    assert "done" in event_names

