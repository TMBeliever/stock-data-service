import json
import logging
from typing import AsyncGenerator, List, Optional, Dict, Any
import httpx
from ai_core.base import BaseAIProvider
from ai_core.config import ai_config
from ai_core.models import (
    Message, AIResponse, StreamChunk, ToolDefinition, ToolCall, UsageInfo
)

logger = logging.getLogger(__name__)

class APIKeyProvider(BaseAIProvider):
    """
    OpenAI-Compatible API Key 驱动：
    适用于 DeepSeek、OpenAI、Claude (通过网关)、通义千问、vLLM、Ollama 等所有标准 OpenAI 规范接口。
    """
    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        timeout: Optional[float] = None
    ):
        self.base_url = (base_url or ai_config.OPENAI_BASE_URL).rstrip("/")
        self.api_key = api_key or ai_config.OPENAI_API_KEY
        self.model = model or ai_config.OPENAI_MODEL
        self.timeout = timeout or ai_config.HTTP_TIMEOUT

    @property
    def provider_type(self) -> str:
        return "key"

    def _get_headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _prepare_payload(
        self,
        messages: List[Message],
        tools: Optional[List[ToolDefinition]] = None,
        stream: bool = False,
        **kwargs
    ) -> Dict[str, Any]:
        """构建 OpenAI 标准聊天请求体"""
        serialized_messages: List[Dict[str, Any]] = []
        for m in messages:
            msg_dict: Dict[str, Any] = {"role": m.role}
            if m.content is not None:
                msg_dict["content"] = m.content
            if m.tool_calls:
                msg_dict["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": tc.raw_arguments or json.dumps(tc.arguments, ensure_ascii=False)
                        }
                    }
                    for tc in m.tool_calls
                ]
            if m.tool_call_id:
                msg_dict["tool_call_id"] = m.tool_call_id
            if m.name:
                msg_dict["name"] = m.name
            serialized_messages.append(msg_dict)

        payload: Dict[str, Any] = {
            "model": kwargs.get("model") or self.model,
            "messages": serialized_messages,
            "stream": stream,
        }

        if tools:
            payload["tools"] = [t.to_openai_dict() for t in tools]

        # 传递用户自定义的 temperature、max_tokens 等参数
        for k in ["temperature", "max_tokens", "top_p", "frequency_penalty", "presence_penalty"]:
            if k in kwargs and kwargs[k] is not None:
                payload[k] = kwargs[k]

        return payload

    async def generate(
        self,
        messages: List[Message],
        tools: Optional[List[ToolDefinition]] = None,
        **kwargs
    ) -> AIResponse:
        """非流式调用：等待完整生成并返回结构化响应"""
        url = f"{self.base_url}/chat/completions"
        payload = self._prepare_payload(messages, tools, stream=False, **kwargs)
        headers = self._get_headers()
        timeout = kwargs.get("timeout", self.timeout)

        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code != 200:
                raise RuntimeError(
                    f"[APIKeyProvider] 请求失败 HTTP {resp.status_code}: {resp.text}"
                )

            data = resp.json()
            choices = data.get("choices", [])
            if not choices:
                return AIResponse(
                    content="",
                    model=data.get("model", self.model),
                    provider_type="key",
                    raw_response=data
                )

            first_choice = choices[0]
            msg = first_choice.get("message", {})
            content = msg.get("content") or ""
            finish_reason = first_choice.get("finish_reason")

            # 解析工具调用
            parsed_tool_calls: Optional[List[ToolCall]] = None
            if "tool_calls" in msg and msg["tool_calls"]:
                parsed_tool_calls = []
                for tc in msg["tool_calls"]:
                    func = tc.get("function", {})
                    raw_args = func.get("arguments", "{}")
                    try:
                        args = json.loads(raw_args)
                    except Exception:
                        args = {}
                    parsed_tool_calls.append(ToolCall(
                        id=tc.get("id", ""),
                        name=func.get("name", ""),
                        arguments=args,
                        raw_arguments=raw_args
                    ))

            # 统计 token 消耗
            usage_dict = data.get("usage")
            usage = None
            if usage_dict:
                usage = UsageInfo(
                    prompt_tokens=usage_dict.get("prompt_tokens", 0),
                    completion_tokens=usage_dict.get("completion_tokens", 0),
                    total_tokens=usage_dict.get("total_tokens", 0)
                )

            return AIResponse(
                content=content,
                model=data.get("model", self.model),
                provider_type="key",
                tool_calls=parsed_tool_calls,
                usage=usage,
                finish_reason=finish_reason,
                raw_response=data
            )

    async def generate_stream(
        self,
        messages: List[Message],
        tools: Optional[List[ToolDefinition]] = None,
        **kwargs
    ) -> AsyncGenerator[StreamChunk, None]:
        """流式调用：基于 SSE 逐 Token 异步产出 StreamChunk"""
        url = f"{self.base_url}/chat/completions"
        payload = self._prepare_payload(messages, tools, stream=True, **kwargs)
        headers = self._get_headers()
        timeout = kwargs.get("timeout", self.timeout)

        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream("POST", url, headers=headers, json=payload) as response:
                if response.status_code != 200:
                    error_text = await response.aread()
                    raise RuntimeError(
                        f"[APIKeyProvider Stream] HTTP {response.status_code}: {error_text.decode('utf-8', errors='replace')}"
                    )

                async for line in response.aiter_lines():
                    clean_line = line.strip()
                    if not clean_line or clean_line.startswith(":"):
                        continue
                    if not clean_line.startswith("data:"):
                        continue

                    data_str = clean_line[len("data:"):].strip()
                    if data_str == "[DONE]":
                        yield StreamChunk(finish_reason="stop")
                        break

                    try:
                        chunk_json = json.loads(data_str)
                    except Exception:
                        continue

                    choices = chunk_json.get("choices", [])
                    if not choices:
                        # 某些模型会在末尾单独推送 usage
                        if "usage" in chunk_json and chunk_json["usage"]:
                            u = chunk_json["usage"]
                            yield StreamChunk(
                                usage=UsageInfo(
                                    prompt_tokens=u.get("prompt_tokens", 0),
                                    completion_tokens=u.get("completion_tokens", 0),
                                    total_tokens=u.get("total_tokens", 0)
                                ),
                                raw_data=chunk_json
                            )
                        continue

                    choice = choices[0]
                    delta = choice.get("delta", {})
                    content_delta = delta.get("content") or ""
                    finish_reason = choice.get("finish_reason")

                    yield StreamChunk(
                        delta=content_delta,
                        role=delta.get("role"),
                        finish_reason=finish_reason,
                        raw_data=chunk_json
                    )
