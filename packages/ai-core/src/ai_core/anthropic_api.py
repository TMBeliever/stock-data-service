import json
import time
import uuid
import hashlib
from typing import Optional, List, Dict, Any, Union, AsyncGenerator
from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from ai_core.config import ai_config
from ai_core.models import Message, resolve_agt_model
from ai_core.orchestrator import ai_orchestrator
from ai_core.openai_api import verify_openai_api_key

anthropic_router = APIRouter(
    tags=["Anthropic Compatible API"],
    dependencies=[Depends(verify_openai_api_key)]
)

class AnthropicMessage(BaseModel):
    """Anthropic 单条消息结构"""
    role: str = Field(..., description="user 或 assistant")
    content: Union[str, List[Dict[str, Any]]] = Field(..., description="文本内容或结构化 ContentBlock 列表")

class AnthropicMessagesRequest(BaseModel):
    """Anthropic 标准 POST /v1/messages 请求体"""
    model: str = Field("claude-3-5-sonnet-20241022", description="模型标识符")
    messages: List[AnthropicMessage] = Field(..., description="多轮对话列表")
    system: Optional[Union[str, List[Dict[str, Any]]]] = Field(None, description="系统级 Prompt")
    max_tokens: Optional[int] = Field(4096, description="最大生成 Token 数")
    stream: Optional[bool] = Field(False, description="是否启用 SSE 流式输出")
    temperature: Optional[float] = Field(None, ge=0.0, le=1.0, description="采样随机度")
    tools: Optional[List[Dict[str, Any]]] = Field(None, description="可选挂载的工具列表")
    metadata: Optional[Dict[str, Any]] = Field(None, description="元数据 (如 user_id 等)")

def _extract_text_content(content: Any) -> str:
    """提取 Anthropic 格式（支持纯字符串或 ContentBlock 数组）中的纯文本内容"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text" and "text" in item:
                    parts.append(str(item["text"]))
                elif item.get("type") == "tool_result" and "content" in item:
                    parts.append(_extract_text_content(item["content"]))
                elif "text" in item:
                    parts.append(str(item["text"]))
            elif hasattr(item, "text") and item.text:
                parts.append(str(item.text))
        return "\n".join(parts)
    return str(content or "")

def _to_internal_messages(req: AnthropicMessagesRequest) -> List[Message]:
    """将 Anthropic 请求转换为内部通用 Message 列表"""
    msgs: List[Message] = []

    # 1. 提取顶层 system prompt
    if req.system:
        system_text = _extract_text_content(req.system).strip()
        if system_text:
            msgs.append(Message.system(system_text))

    # 2. 提取多轮问答
    for m in req.messages:
        text = _extract_text_content(m.content)
        if m.role == "user":
            msgs.append(Message.user(text))
        elif m.role == "assistant":
            msgs.append(Message.assistant(text))
        else:
            msgs.append(Message(role=m.role, content=text))

    return msgs

def _resolve_provider_and_kwargs(req: AnthropicMessagesRequest) -> tuple[str, Dict[str, Any]]:
    """
    模型驱动分流：
    支持 agt-* 模型矩阵、Claude 原生模型 (自动映射到 Antigravity 宿主机模型)、
    以及指定外部 key 的模型。
    """
    model_name = (req.model or "").strip()
    extra_kwargs: Dict[str, Any] = {}

    if req.temperature is not None:
        extra_kwargs["temperature"] = req.temperature

    provider_type, target_model = resolve_agt_model(model_name)
    extra_kwargs["effort"] = "medium"
    extra_kwargs["reasoning_effort"] = "medium"
    if provider_type == "cli":
        extra_kwargs["executable"] = "agy"
        extra_kwargs["model"] = target_model
    else:
        extra_kwargs["model"] = target_model or ai_config.OPENAI_MODEL

    return provider_type, extra_kwargs

@anthropic_router.post("/v1/messages/count_tokens")
@anthropic_router.post("/messages/count_tokens")
async def count_tokens(req: AnthropicMessagesRequest):
    """
    Anthropic 标准 Token 计数端点：
    供 Claude CLI / SDK 在生成前预先评估上下文长度，防止客户端报错。
    """
    total_chars = 0
    if req.system:
        total_chars += len(_extract_text_content(req.system))
    for m in req.messages:
        total_chars += len(_extract_text_content(m.content))

    estimated_tokens = max(1, total_chars // 4)
    return {"input_tokens": estimated_tokens}

@anthropic_router.post("/v1/messages")
@anthropic_router.post("/messages")
async def messages_completion(req: AnthropicMessagesRequest):
    """
    Anthropic 标准 POST /v1/messages 端点：
    完整兼容 Claude CLI (Claude Code) 与 Anthropic SDK，支持流式与非流式输出。
    """
    if not req.messages or len(req.messages) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Anthropic request must contain a non-empty 'messages' list."
        )

    internal_messages = _to_internal_messages(req)
    provider_type, extra_kwargs = _resolve_provider_and_kwargs(req)

    msg_id = f"msg_{uuid.uuid4().hex[:24]}"

    # 1. 流式响应 (stream=True) —— 严格对齐 Anthropic SSE 事件流协议
    if req.stream:
        async def anthropic_stream_generator() -> AsyncGenerator[Dict[str, Any], None]:
            try:
                # Event 1: message_start
                start_payload = {
                    "type": "message_start",
                    "message": {
                        "id": msg_id,
                        "type": "message",
                        "role": "assistant",
                        "content": [],
                        "model": req.model,
                        "stop_reason": None,
                        "stop_sequence": None,
                        "usage": {"input_tokens": 10, "output_tokens": 1}
                    }
                }
                yield {"event": "message_start", "data": json.dumps(start_payload, ensure_ascii=False)}

                # Event 2: content_block_start
                block_start_payload = {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {"type": "text", "text": ""}
                }
                yield {"event": "content_block_start", "data": json.dumps(block_start_payload, ensure_ascii=False)}

                # Event 3: content_block_delta (逐块转发增量文本)
                total_chars = 0
                async for chunk in ai_orchestrator.generate_stream(
                    messages=internal_messages,
                    provider_type=provider_type,
                    **extra_kwargs
                ):
                    if chunk.delta:
                        total_chars += len(chunk.delta)
                        delta_payload = {
                            "type": "content_block_delta",
                            "index": 0,
                            "delta": {"type": "text_delta", "text": chunk.delta}
                        }
                        yield {"event": "content_block_delta", "data": json.dumps(delta_payload, ensure_ascii=False)}

                # Event 4: content_block_stop
                block_stop_payload = {
                    "type": "content_block_stop",
                    "index": 0
                }
                yield {"event": "content_block_stop", "data": json.dumps(block_stop_payload, ensure_ascii=False)}

                # Event 5: message_delta (结束原因与输出 token)
                msg_delta_payload = {
                    "type": "message_delta",
                    "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                    "usage": {"output_tokens": max(1, total_chars // 4)}
                }
                yield {"event": "message_delta", "data": json.dumps(msg_delta_payload, ensure_ascii=False)}

                # Event 6: message_stop
                yield {"event": "message_stop", "data": json.dumps({"type": "message_stop"}, ensure_ascii=False)}

            except Exception as e:
                err_payload = {
                    "type": "error",
                    "error": {
                        "type": "api_error",
                        "message": str(e)
                    }
                }
                yield {"event": "error", "data": json.dumps(err_payload, ensure_ascii=False)}

        return EventSourceResponse(anthropic_stream_generator())

    # 2. 非流式响应 (stream=False)
    try:
        response = await ai_orchestrator.generate(
            messages=internal_messages,
            provider_type=provider_type,
            **extra_kwargs
        )
        content_text = response.content or ""
        total_input_chars = sum(len(m.content or "") for m in internal_messages)

        return {
            "id": msg_id,
            "type": "message",
            "role": "assistant",
            "model": req.model,
            "content": [
                {
                    "type": "text",
                    "text": content_text
                }
            ],
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {
                "input_tokens": max(1, total_input_chars // 4),
                "output_tokens": max(1, len(content_text) // 4)
            }
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Anthropic message generation failed: {str(e)}"
        )
