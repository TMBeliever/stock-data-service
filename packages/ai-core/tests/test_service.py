import pytest
from httpx import AsyncClient, ASGITransport
from ai_core.service import app

@pytest.mark.asyncio
async def test_service_health():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert data["service"] == "ai-core"
        assert "default_model" in data

@pytest.mark.asyncio
async def test_service_root():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/")
        assert resp.status_code == 200
        assert resp.json()["docs_url"] == "/docs"

@pytest.mark.asyncio
async def test_service_generate_validation_error():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 既无 prompt 又无 messages 时应返回 400
        resp = await client.post("/api/v1/ai/generate", json={})
        assert resp.status_code == 400

@pytest.mark.asyncio
async def test_service_stream_post_mock(monkeypatch):
    """测试 SSE 流式端点输出"""
    from ai_core.models import StreamChunk

    async def mock_stream(*args, **kwargs):
        yield StreamChunk(delta="Hello")
        yield StreamChunk(delta=" world")
        yield StreamChunk(finish_reason="stop")

    from ai_core.orchestrator import ai_orchestrator
    monkeypatch.setattr(ai_orchestrator, "generate_stream", mock_stream)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/v1/ai/stream", json={"prompt": "test"})
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")
        text = resp.text
        assert "Hello" in text
        assert "world" in text

@pytest.mark.asyncio
async def test_service_stream_get_mock(monkeypatch):
    """测试 GET SSE 流式端点"""
    from ai_core.models import StreamChunk

    async def mock_stream(*args, **kwargs):
        yield StreamChunk(delta="GET_STREAM_OK")

    from ai_core.orchestrator import ai_orchestrator
    monkeypatch.setattr(ai_orchestrator, "generate_stream", mock_stream)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/ai/stream", params={"prompt": "hi"})
        assert resp.status_code == 200
        assert "GET_STREAM_OK" in resp.text
