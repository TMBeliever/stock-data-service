import json
import asyncio
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
async def test_anthropic_stateless_execution(monkeypatch):
    """测试 Anthropic 接口完全无状态，不注入 session_id 累加历史"""
    captured_kwargs = {}
    async def mock_generate(*args, **kwargs):
        captured_kwargs.update(kwargs)
        return AIResponse(content="stateless-ok", model="agy", provider_type="cli")

    from ai_core.orchestrator import ai_orchestrator
    monkeypatch.setattr(ai_orchestrator, "generate", mock_generate)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "model": "claude-3-5-sonnet",
            "messages": [{"role": "user", "content": "Stateless question"}],
            "stream": False
        }
        resp = await client.post("/v1/messages", headers=VALID_ANTHROPIC_HEADER, json=payload)
        assert resp.status_code == 200
        # 确认完全无状态，未注入 session_id
        assert captured_kwargs.get("session_id") is None

@pytest.mark.asyncio
async def test_anthropic_agt_model_routing(monkeypatch):
    """测试 agt-* 模型矩阵及 Claude 原生模型通过 Anthropic 接口正确路由"""
    captured_kwargs = {}
    async def mock_generate(*args, **kwargs):
        captured_kwargs.update(kwargs)
        return AIResponse(content="anthropic-agt", model="agy", provider_type="cli")

    from ai_core.orchestrator import ai_orchestrator
    monkeypatch.setattr(ai_orchestrator, "generate", mock_generate)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. 显式 agt-gemini-3.8-flash
        payload1 = {
            "model": "agt-gemini-3.8-flash",
            "messages": [{"role": "user", "content": "Hello"}],
            "stream": False
        }
        resp1 = await client.post("/v1/messages", headers=VALID_ANTHROPIC_HEADER, json=payload1)
        assert resp1.status_code == 200
        assert captured_kwargs.get("provider_type") == "cli"
        assert captured_kwargs.get("model") == "gemini-3.8-flash"

        # 2. 原生 Claude 请求自动映射到 claude-sonnet-4.6
        payload2 = {
            "model": "claude-3-7-sonnet-20250219",
            "messages": [{"role": "user", "content": "Hello"}],
            "stream": False
        }
        resp2 = await client.post("/v1/messages", headers=VALID_ANTHROPIC_HEADER, json=payload2)
        assert resp2.status_code == 200
        assert captured_kwargs.get("provider_type") == "cli"
        assert captured_kwargs.get("model") == "claude-sonnet-4-6"

@pytest.mark.asyncio
async def test_anthropic_client_disconnect_cancels_and_cleans_worker(monkeypatch):
    """验证客户端中途断开 SSE 连接时 (如 Ctrl+C)，ASGI 层触发取消并立即强杀清理底层 Worker"""
    import sys
    from ai_core.process_pool import prewarmed_process_pool, PrewarmedProcess

    # 模拟一个持续输出慢速 Chunk 的子进程
    code = (
        "import sys, time\n"
        "sys.stdin.read()\n"
        "for i in range(100):\n"
        "    print(f'TOKEN_{i}', flush=True)\n"
        "    time.sleep(0.1)\n"
    )
    async def mock_spawn(*args, **kwargs):
        p = await asyncio.create_subprocess_exec(
            sys.executable, "-c", code,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        return PrewarmedProcess(proc=p, created_at=0.0)

    monkeypatch.setattr(prewarmed_process_pool, "_spawn_worker", mock_spawn)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 建立流式连接并在接收到第一个 token 后主动跳出断开连接 (模拟 Ctrl+C)
        async with client.stream(
            "POST", "/v1/messages",
            headers=VALID_ANTHROPIC_HEADER,
            json={
                "model": "agt-gemini-3.8-flash",
                "messages": [{"role": "user", "content": "test"}],
                "stream": True
            }
        ) as response:
            assert response.status_code == 200
            async for line in response.aiter_lines():
                if "TOKEN_" in line:
                    break
        # 客户端连接已关闭，断开信号传递到服务端

    # 稍作等待让事件循环处理 ASGI Disconnect
    await asyncio.sleep(0.2)

    # 验证活跃进程集合已被完全清空，无任何僵尸进程滞留
    assert len(prewarmed_process_pool._active_processes) == 0


