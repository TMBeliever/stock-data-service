import json
import pytest
from httpx import AsyncClient, ASGITransport
from ai_core.service import app
from ai_core.models import AIResponse, StreamChunk
from ai_core.config import ai_config

VALID_AUTH_HEADER = {"Authorization": f"Bearer {ai_config.GATEWAY_API_KEY}"}

@pytest.mark.asyncio
async def test_openai_unauthorized_rejection():
    """测试未携带有效 API Key 时被 401 拦截拒绝"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. 完全不带 Authorization 头
        resp = await client.get("/v1/models")
        assert resp.status_code == 401
        data = resp.json()
        assert "error" in data["detail"]
        assert data["detail"]["error"]["code"] == "invalid_api_key"

        # 2. 携带错误的 API Key
        resp2 = await client.post(
            "/v1/chat/completions",
            headers={"Authorization": "Bearer sk-wrong-key"},
            json={"model": "agy", "messages": [{"role": "user", "content": "hi"}]}
        )
        assert resp2.status_code == 401

@pytest.mark.asyncio
async def test_openai_list_models():
    """测试携带正确 API Key 访问 /v1/models"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/models", headers=VALID_AUTH_HEADER)
        assert resp.status_code == 200
        data = resp.json()
        assert data["object"] == "list"
        model_ids = [m["id"] for m in data["data"]]
        assert "agy" in model_ids
        assert "gemini-flash-lite-latest" in model_ids

@pytest.mark.asyncio
async def test_openai_chat_completions_non_stream(monkeypatch):
    """测试 OpenAI /v1/chat/completions 非流式调用"""
    captured_kwargs = {}
    async def mock_generate(*args, **kwargs):
        captured_kwargs.update(kwargs)
        return AIResponse(
            content="Hello from OpenAI adapter!",
            model=kwargs.get("model", "agy"),
            provider_type=kwargs.get("provider_type", "cli")
        )

    from ai_core.orchestrator import ai_orchestrator
    monkeypatch.setattr(ai_orchestrator, "generate", mock_generate)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "model": "agy",
            "messages": [
                {"role": "system", "content": "You are an assistant"},
                {"role": "user", "content": "Hi there!"}
            ],
            "stream": False,
            "temperature": 0.5
        }
        resp = await client.post("/v1/chat/completions", headers=VALID_AUTH_HEADER, json=payload)
        assert resp.status_code == 200
        data = resp.json()

        # 校验符合 OpenAI 标准结构
        assert data["object"] == "chat.completion"
        assert data["model"] == "agy"
        assert len(data["choices"]) == 1
        assert data["choices"][0]["message"]["role"] == "assistant"
        assert data["choices"][0]["message"]["content"] == "Hello from OpenAI adapter!"
        assert data["choices"][0]["finish_reason"] == "stop"
        assert data["usage"]["total_tokens"] > 0

        # 校验正确路由到了 CLI 驱动
        assert captured_kwargs.get("provider_type") == "cli"
        assert captured_kwargs.get("executable") == "agy"

@pytest.mark.asyncio
async def test_openai_chat_completions_stream(monkeypatch):
    """测试 OpenAI /v1/chat/completions SSE 流式调用"""
    async def mock_stream(*args, **kwargs):
        yield StreamChunk(delta="OpenAI ")
        yield StreamChunk(delta="Stream ")
        yield StreamChunk(delta="Success!")
        yield StreamChunk(finish_reason="stop")

    from ai_core.orchestrator import ai_orchestrator
    monkeypatch.setattr(ai_orchestrator, "generate_stream", mock_stream)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "model": "agy",
            "messages": [
                {"role": "user", "content": "Count to 3"}
            ],
            "stream": True
        }
        resp = await client.post("/v1/chat/completions", headers=VALID_AUTH_HEADER, json=payload)
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")

        raw_text = resp.text
        # 必须包含 OpenAI 标准终止标
        assert "data: [DONE]" in raw_text
        assert "OpenAI " in raw_text
        assert "chat.completion.chunk" in raw_text

@pytest.mark.asyncio
async def test_openai_chat_completions_key_routing(monkeypatch):
    """测试非 agy 模型自动路由到 key 驱动"""
    captured_kwargs = {}
    async def mock_generate(*args, **kwargs):
        captured_kwargs.update(kwargs)
        return AIResponse(
            content="Key Response",
            model="minimax/minimax-m3:free",
            provider_type="key"
        )

    from ai_core.orchestrator import ai_orchestrator
    monkeypatch.setattr(ai_orchestrator, "generate", mock_generate)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "model": "minimax/minimax-m3:free",
            "messages": [{"role": "user", "content": "Hello"}],
            "stream": False
        }
        resp = await client.post("/v1/chat/completions", headers=VALID_AUTH_HEADER, json=payload)
        assert resp.status_code == 200
        assert captured_kwargs.get("provider_type") == "key"
        assert captured_kwargs.get("model") == "minimax/minimax-m3:free"
