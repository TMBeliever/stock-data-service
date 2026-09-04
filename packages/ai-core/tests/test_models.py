import pytest
from ai_core.models import (
    Message, ToolDefinition, ToolCall, StreamChunk, AIResponse, UsageInfo
)

def test_message_helpers():
    sys_msg = Message.system("You are a quant assistant.")
    assert sys_msg.role == "system"
    assert sys_msg.content == "You are a quant assistant."

    user_msg = Message.user("Analyze 513100.SH")
    assert user_msg.role == "user"
    assert user_msg.content == "Analyze 513100.SH"

    tool_call = ToolCall(id="call_1", name="calc", arguments={"x": 10})
    ast_msg = Message.assistant(content="Thinking...", tool_calls=[tool_call])
    assert ast_msg.role == "assistant"
    assert len(ast_msg.tool_calls) == 1
    assert ast_msg.tool_calls[0].name == "calc"

    tool_res = Message.tool_result(tool_call_id="call_1", content="20")
    assert tool_res.role == "tool"
    assert tool_res.tool_call_id == "call_1"
    assert tool_res.content == "20"

def test_tool_definition_to_openai():
    tool = ToolDefinition(
        name="get_kline",
        description="Query stock historical kline data",
        parameters={
            "type": "object",
            "properties": {
                "symbol": {"type": "string"}
            },
            "required": ["symbol"]
        }
    )
    d = tool.to_openai_dict()
    assert d["type"] == "function"
    assert d["function"]["name"] == "get_kline"
    assert "parameters" in d["function"]

def test_stream_chunk_and_response():
    chunk = StreamChunk(delta="Hello", role="assistant")
    assert chunk.delta == "Hello"
    assert chunk.role == "assistant"

    usage = UsageInfo(prompt_tokens=10, completion_tokens=20, total_tokens=30)
    resp = AIResponse(
        content="Final answer",
        model="test-model",
        provider_type="key",
        usage=usage
    )
    assert resp.content == "Final answer"
    assert resp.provider_type == "key"
    assert resp.usage.total_tokens == 30
