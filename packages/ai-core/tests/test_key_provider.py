import pytest
from ai_core.providers.key_provider import APIKeyProvider
from ai_core.models import Message

@pytest.mark.asyncio
async def test_live_key_provider_generation():
    """真实联调测试：连接 http://43.155.186.45:3000/v1 验证完整非流式生成"""
    provider = APIKeyProvider(
        base_url="http://43.155.186.45:3000/v1",
        api_key="sk-W91gp63k2tmArgtL8wxIMoQaYj8CmFtumeF9T34xSpuIZj34",
        model="gemini-flash-lite-latest",
        timeout=90.0
    )

    messages = [
        Message.system("You are a brief assistant."),
        Message.user("Respond with the exact word 'QUANT_AI_OK' only.")
    ]

    response = await provider.generate(messages)
    assert response.provider_type == "key"
    assert "QUANT_AI_OK" in response.content.upper()
    assert response.content != ""
    assert response.model != ""

@pytest.mark.asyncio
async def test_live_key_provider_stream():
    """真实联调测试：连接 http://43.155.186.45:3000/v1 验证逐 Token 流式接收"""
    provider = APIKeyProvider(
        base_url="http://43.155.186.45:3000/v1",
        api_key="sk-W91gp63k2tmArgtL8wxIMoQaYj8CmFtumeF9T34xSpuIZj34",
        model="gemini-flash-lite-latest",
        timeout=90.0
    )

    messages = [
        Message.user("Count from 1 to 3 separated by spaces.")
    ]

    collected_deltas = []
    async for chunk in provider.generate_stream(messages):
        if chunk.delta:
            collected_deltas.append(chunk.delta)

    full_text = "".join(collected_deltas)
    assert len(collected_deltas) >= 1
    assert "1" in full_text
    assert "3" in full_text

@pytest.mark.asyncio
async def test_generate_text_helper():
    """测试便捷纯文本生成接口"""
    provider = APIKeyProvider(
        base_url="http://43.155.186.45:3000/v1",
        api_key="sk-W91gp63k2tmArgtL8wxIMoQaYj8CmFtumeF9T34xSpuIZj34",
        model="gemini-flash-lite-latest",
        timeout=90.0
    )

    text = await provider.generate_text("Say 'Hello' only.")
    assert "Hello" in text
