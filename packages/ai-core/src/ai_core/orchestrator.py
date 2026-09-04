from typing import Optional, List, AsyncGenerator
from ai_core.base import BaseAIProvider
from ai_core.config import ai_config
from ai_core.models import Message, AIResponse, StreamChunk, ToolDefinition
from ai_core.providers.key_provider import APIKeyProvider
from ai_core.providers.cli_provider import CLIProcessProvider

class AIOrchestrator:
    """
    AI 统一调度中枢与门面工厂：
    按需构建或分发 APIKeyProvider / CLIProcessProvider，提供全局统一的调用入口。
    """
    def __init__(self, default_provider: Optional[str] = None):
        self.default_provider_type = default_provider or ai_config.DEFAULT_PROVIDER

    def get_provider(
        self,
        provider_type: Optional[str] = None,
        **kwargs
    ) -> BaseAIProvider:
        """根据类型获取对应的 AI 驱动实例 ('key' 或 'cli')"""
        ptype = (provider_type or self.default_provider_type).lower()

        if ptype == "key":
            key_kwargs = {k: v for k, v in kwargs.items() if k in ["base_url", "api_key", "model", "timeout"]}
            return APIKeyProvider(**key_kwargs)
        elif ptype == "cli":
            cli_kwargs = {k: v for k, v in kwargs.items() if k in ["executable", "args_template", "timeout", "cwd", "env"]}
            return CLIProcessProvider(**cli_kwargs)
        else:
            raise ValueError(f"未知的 AI 提供方类型: '{ptype}', 可选为 'key' 或 'cli'")

    async def generate(
        self,
        messages: List[Message],
        provider_type: Optional[str] = None,
        tools: Optional[List[ToolDefinition]] = None,
        **kwargs
    ) -> AIResponse:
        """全局便捷调用：生成响应"""
        provider = self.get_provider(provider_type=provider_type, **kwargs)
        return await provider.generate(messages, tools=tools, **kwargs)

    async def generate_stream(
        self,
        messages: List[Message],
        provider_type: Optional[str] = None,
        tools: Optional[List[ToolDefinition]] = None,
        **kwargs
    ) -> AsyncGenerator[StreamChunk, None]:
        """全局便捷调用：流式生成"""
        provider = self.get_provider(provider_type=provider_type, **kwargs)
        async for chunk in provider.generate_stream(messages, tools=tools, **kwargs):
            yield chunk

    async def generate_text(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        provider_type: Optional[str] = None,
        **kwargs
    ) -> str:
        """全局便捷调用：纯文本生成"""
        provider = self.get_provider(provider_type=provider_type, **kwargs)
        return await provider.generate_text(prompt, system_prompt=system_prompt, **kwargs)

    async def generate_text_stream(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        provider_type: Optional[str] = None,
        **kwargs
    ) -> AsyncGenerator[str, None]:
        """全局便捷调用：纯文本流式生成"""
        provider = self.get_provider(provider_type=provider_type, **kwargs)
        async for delta in provider.generate_text_stream(prompt, system_prompt=system_prompt, **kwargs):
            yield delta

# 预置单例门面
ai_orchestrator = AIOrchestrator()
