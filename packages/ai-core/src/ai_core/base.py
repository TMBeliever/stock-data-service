from abc import ABC, abstractmethod
from typing import AsyncGenerator, List, Optional
from ai_core.models import Message, AIResponse, StreamChunk, ToolDefinition

class BaseAIProvider(ABC):
    """所有 AI 模型驱动的抽象协议基类"""

    @property
    @abstractmethod
    def provider_type(self) -> str:
        """驱动类型标识 (例如 'key' 或 'cli')"""
        pass

    @abstractmethod
    async def generate(
        self,
        messages: List[Message],
        tools: Optional[List[ToolDefinition]] = None,
        **kwargs
    ) -> AIResponse:
        """单次完整文本/工具调用生成"""
        pass

    @abstractmethod
    async def generate_stream(
        self,
        messages: List[Message],
        tools: Optional[List[ToolDefinition]] = None,
        **kwargs
    ) -> AsyncGenerator[StreamChunk, None]:
        """流式生成 (逐 Token 产生增量)"""
        pass

    async def generate_text(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        **kwargs
    ) -> str:
        """便捷方法：纯文本单次生成"""
        msgs: List[Message] = []
        if system_prompt:
            msgs.append(Message.system(system_prompt))
        msgs.append(Message.user(prompt))
        res = await self.generate(msgs, **kwargs)
        return res.content

    async def generate_text_stream(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        **kwargs
    ) -> AsyncGenerator[str, None]:
        """便捷方法：纯文本流式生成"""
        msgs: List[Message] = []
        if system_prompt:
            msgs.append(Message.system(system_prompt))
        msgs.append(Message.user(prompt))
        async for chunk in self.generate_stream(msgs, **kwargs):
            if chunk.delta:
                yield chunk.delta
