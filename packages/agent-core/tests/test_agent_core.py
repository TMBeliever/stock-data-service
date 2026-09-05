import json
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

    # 超长文本截断测试 (首尾双向保留)
    long_text = "HEAD_START\n" + "Line\n" * 20 + "A" * 300 + "\nTAIL_END"
    truncated = governor.truncate_observation(long_text)
    assert len(truncated) > 0
    assert "Output truncated by TokenGovernor" in truncated
    assert "HEAD_START" in truncated
    assert "TAIL_END" in truncated

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

@pytest.mark.asyncio
async def test_execution_mode_confirm_sensitive_interception():
    """测试敏感模式下未授权工具调用被成功拦截，返回 requires_approval"""
    registry = ToolRegistry()

    @tool(name="run_command", description="执行 Shell 命令")
    def mock_shell(command: str) -> str:
        return f"Executed: {command}"

    registry.register(mock_shell)
    agent = BaseAgent(name="SecurityAgent", tool_registry=registry)

    async def mock_llm_generate(messages, tools, model=None, provider=None, temperature=None):
        # 只要执行过工具，模型即完成任务并输出总结 (对标真实 LLM 行为)
        has_tool_res = any(m.role == "tool" for m in messages)
        if has_tool_res:
            return {"content": "Docker 容器已处于运行状态", "tool_calls": []}
        return {
            "content": "",
            "tool_calls": [
                {
                    "id": "call_docker_123",
                    "name": "run_command",
                    "arguments": {"command": "docker ps -a"}
                }
            ]
        }

    agent._call_llm_generate = mock_llm_generate

    # 未授权调用：应当拦截并产出 requires_approval
    events = []
    async for event in agent.stream_chat(
        prompt="查看 docker 容器",
        execution_mode="confirm_sensitive",
        sensitive_tools=["run_command"]
    ):
        events.append(event)

    event_names = [e["event"] for e in events]
    assert "requires_approval" in event_names
    assert "done" in event_names

    # 验证已授权调用：传入 approved_tool_calls 后应当顺利执行并自然完成
    approved_events = []
    async for event in agent.stream_chat(
        prompt="查看 docker 容器",
        execution_mode="confirm_sensitive",
        sensitive_tools=["run_command"],
        approved_tool_calls=["call_docker_123"]
    ):
        approved_events.append(event)

    approved_event_names = [e["event"] for e in approved_events]
    assert "requires_approval" not in approved_event_names
    assert "tool_call" in approved_event_names
    assert "tool_result" in approved_event_names
    assert "message" in approved_event_names

    # 验证直接携带 approved_tool_call 恢复执行 (杜绝死循环)
    resumed_events = []
    async for event in agent.stream_chat(
        prompt="查看 docker 容器",
        execution_mode="confirm_sensitive",
        sensitive_tools=["run_command"],
        approved_tool_call={
            "id": "call_docker_123",
            "name": "run_command",
            "arguments": {"command": "docker ps -a"},
            "step": 1
        }
    ):
        resumed_events.append(event)

    resumed_names = [e["event"] for e in resumed_events]
    assert "requires_approval" not in resumed_names
    assert "tool_call" in resumed_names
    assert "tool_result" in resumed_names
    assert "message" in resumed_names


@pytest.mark.asyncio
async def test_unbounded_steps_natural_completion():
    """测试对齐 DSH 的无限制步数模式 (max_steps=0): 模型可执行多步并在完成时自然终结"""
    registry = ToolRegistry()

    step_counter = 0

    @tool(name="step_runner", description="推进子任务")
    def step_runner(idx: int) -> str:
        return f"Completed step {idx}"

    registry.register(step_runner)
    # max_steps=0 代表无限制模式
    agent = BaseAgent(name="UnboundedAgent", tool_registry=registry, max_steps=0)

    async def mock_multi_step_llm(messages, tools, model=None, provider=None, temperature=None):
        nonlocal step_counter
        step_counter += 1
        if step_counter <= 3:
            # 前 3 步连续调用不同参数的工具
            return {
                "content": "",
                "tool_calls": [{
                    "id": f"call_{step_counter}",
                    "name": "step_runner",
                    "arguments": {"idx": step_counter}
                }]
            }
        # 第 4 步完成任务，输出纯文本
        return {"content": "所有复杂任务步骤均已顺利执行完毕！", "tool_calls": []}

    agent._call_llm_generate = mock_multi_step_llm

    events = []
    async for event in agent.stream_chat(prompt="执行跨多步的量化任务"):
        events.append(event)

    event_names = [e["event"] for e in events]
    tool_results = [e for e in events if e["event"] == "tool_result"]
    assert len(tool_results) == 3
    assert "done" in event_names
    # 确认没有触发"步数上限"警告
    messages = [e for e in events if e["event"] == "message"]
    full_msg = "".join(json.loads(m["data"]).get("delta", "") for m in messages)
    assert "步数上限" not in full_msg
    assert "所有复杂任务步骤均已顺利执行完毕！" in full_msg


