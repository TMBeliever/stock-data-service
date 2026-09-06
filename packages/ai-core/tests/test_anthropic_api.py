import json
import pytest
from httpx import AsyncClient, ASGITransport
from ai_core.service import app
from ai_core.models import AIResponse, StreamChunk
from ai_core.config import ai_config

VALID_ANTHROPIC_HEADER = {
    "x-api-key": ai_config.GATEWAY_API_KEY,
    "anthropic-version": "2023-06-01"
}

@pytest.mark.asyncio
async def test_anthropic_unauthorized_rejection():
    """测试未携带有效 x-api-key 时被 401 拦截"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 无 header
        resp = await client.post("/v1/messages", json={"messages": [{"role": "user", "content": "hi"}]})
        assert resp.status_code == 401

        # 错误 key
        resp2 = await client.post(
            "/v1/messages",
            headers={"x-api-key": "bad-key"},
            json={"messages": [{"role": "user", "content": "hi"}]}
        )
        assert resp2.status_code == 401

@pytest.mark.asyncio
async def test_anthropic_count_tokens():
    """测试 /v1/messages/count_tokens 计数端点"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "model": "claude-3-5-sonnet-20241022",
            "system": "You are a helpful coding assistant.",
            "messages": [
                {"role": "user", "content": "Write a python script"}
            ]
        }
        resp = await client.post("/v1/messages/count_tokens", headers=VALID_ANTHROPIC_HEADER, json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert "input_tokens" in data
        assert data["input_tokens"] > 0

@pytest.mark.asyncio
async def test_anthropic_messages_non_stream(monkeypatch):
    """测试 Anthropic /v1/messages 非流式生成"""
    captured_kwargs = {}
    async def mock_generate(*args, **kwargs):
        captured_kwargs.update(kwargs)
        return AIResponse(
            content="Hello from Anthropic adapter!",
            model="agy",
            provider_type="cli"
        )

    from ai_core.orchestrator import ai_orchestrator
    monkeypatch.setattr(ai_orchestrator, "generate", mock_generate)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "model": "claude-3-5-sonnet-20241022",
            "system": "You are brief.",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Hello Claude CLI!"}
                    ]
                }
            ],
            "stream": False
        }
        resp = await client.post("/v1/messages", headers=VALID_ANTHROPIC_HEADER, json=payload)
        assert resp.status_code == 200
        data = resp.json()

        # 校验符合 Anthropic 标准结构
        assert data["type"] == "message"
        assert data["role"] == "assistant"
        assert len(data["content"]) == 1
        assert data["content"][0]["type"] == "text"
        assert data["content"][0]["text"] == "Hello from Anthropic adapter!"
        assert data["stop_reason"] == "end_turn"
        assert data["usage"]["output_tokens"] > 0

        # 默认自动路由到 agy 驱动
        assert captured_kwargs.get("provider_type") == "cli"
        assert captured_kwargs.get("executable") == "agy"

@pytest.mark.asyncio
async def test_anthropic_messages_stream(monkeypatch):
    """测试 Anthropic /v1/messages SSE 专属流式事件序列"""
    async def mock_stream(*args, **kwargs):
        yield StreamChunk(delta="Hello ")
        yield StreamChunk(delta="from ")
        yield StreamChunk(delta="Claude!")
        yield StreamChunk(finish_reason="stop")

    from ai_core.orchestrator import ai_orchestrator
    monkeypatch.setattr(ai_orchestrator, "generate_stream", mock_stream)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "model": "claude-3-7-sonnet-20250219",
            "messages": [
                {"role": "user", "content": "Say hello"}
            ],
            "stream": True
        }
        resp = await client.post("/v1/messages", headers=VALID_ANTHROPIC_HEADER, json=payload)
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")

        raw_text = resp.text
        # 必须严格包含 Anthropic 规定的事件序列
        assert "event: message_start" in raw_text
        assert "event: content_block_start" in raw_text
        assert "event: content_block_delta" in raw_text
        assert "event: content_block_stop" in raw_text
        assert "event: message_delta" in raw_text
        assert "event: message_stop" in raw_text
        assert "Claude!" in raw_text

@pytest.mark.asyncio
async def test_anthropic_session_affinity_binding(monkeypatch):
    """测试 Anthropic 请求能自动提取或根据首句生成 session_id 并绑定到 extra_kwargs"""
    captured_kwargs = {}
    async def mock_generate(*args, **kwargs):
        captured_kwargs.update(kwargs)
        return AIResponse(content="ok", model="agy", provider_type="cli")

    from ai_core.orchestrator import ai_orchestrator
    monkeypatch.setattr(ai_orchestrator, "generate", mock_generate)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Case 1: 自动根据首句指纹生成 session_id
        payload1 = {
            "model": "claude-3-5-sonnet",
            "messages": [{"role": "user", "content": "Conversation Topic Alpha"}],
            "stream": False
        }
        await client.post("/v1/messages", headers=VALID_ANTHROPIC_HEADER, json=payload1)
        sess1 = captured_kwargs.get("session_id")
        assert sess1 is not None
        assert sess1.startswith("claude_")

        # Case 2: 携带 metadata.user_id
        payload2 = {
            "model": "claude-3-5-sonnet",
            "messages": [{"role": "user", "content": "Another question"}],
            "metadata": {"user_id": "claude_user_999"},
            "stream": False
        }
        await client.post("/v1/messages", headers=VALID_ANTHROPIC_HEADER, json=payload2)
        assert captured_kwargs.get("session_id") == "claude_user_999"
