import json
import time
import uuid
import hashlib
from typing import Optional, List, Dict, Any, AsyncGenerator
from fastapi import APIRouter, HTTPException, Header, Depends, Query, Security, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from ai_core.config import ai_config
from ai_core.models import Message, ToolDefinition, ToolCall, resolve_agt_model
from ai_core.orchestrator import ai_orchestrator

security = HTTPBearer(auto_error=False)

def verify_openai_api_key(
    auth_cred: Optional[HTTPAuthorizationCredentials] = Security(security),
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None, alias="x-api-key"),
    api_key: Optional[str] = Query(None)
) -> str:
    """严格鉴权：校验调用方是否持有授权的固定 API Key"""
    token = None
    if auth_cred and auth_cred.credentials:
        token = auth_cred.credentials.strip()
    elif authorization:
        if authorization.lower().startswith("bearer "):
            token = authorization[7:].strip()
        else:
            token = authorization.strip()
    elif x_api_key:
        token = x_api_key.strip()
    elif api_key:
        token = api_key.strip()

    expected_key = getattr(ai_config, "GATEWAY_API_KEY", "sk-quant-agy-8f92e10c74b6")
    if not token or token != expected_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": {
                    "message": "Incorrect API key provided. You must provide a valid API key.",
                    "type": "invalid_request_error",
                    "param": None,
                    "code": "invalid_api_key"
                }
            }
        )
    return token

openai_router = APIRouter(
    tags=["OpenAI Compatible API"],
    dependencies=[Depends(verify_openai_api_key)]
)

class OpenAIChatMessage(BaseModel):
    """OpenAI 标准对话消息格式"""
    role: str = Field(..., description="角色: system, user, assistant, tool")
    content: Optional[str] = Field("", description="消息文本内容")
    name: Optional[str] = Field(None, description="可选发送者名称")
    tool_calls: Optional[List[Dict[str, Any]]] = Field(None, description="模型发起的工具调用")
    tool_call_id: Optional[str] = Field(None, description="工具响应 ID")

class OpenAIChatCompletionRequest(BaseModel):
    """OpenAI 标准 /v1/chat/completions 请求体"""
    model: str = Field("agy", description="模型标识符 (如 'agy', 'minimax/minimax-m3:free', 'gemini-flash-lite-latest')")
    messages: List[OpenAIChatMessage] = Field(..., description="完整多轮对话消息列表")
    stream: Optional[bool] = Field(False, description="是否启用 SSE 流式输出")
    temperature: Optional[float] = Field(None, ge=0.0, le=2.0, description="采样随机度")
    max_tokens: Optional[int] = Field(None, description="最大生成 Token 数")
    reasoning_effort: Optional[str] = Field(None, description="思考深度 (low, medium, high)")
    tools: Optional[List[Dict[str, Any]]] = Field(None, description="工具函数声明定义列表")
    user: Optional[str] = Field(None, description="调用端用户/会话唯一标识符")

class OpenAIChoiceMessage(BaseModel):
    role: str = "assistant"
    content: Optional[str] = ""
    tool_calls: Optional[List[Dict[str, Any]]] = None

class OpenAIChoice(BaseModel):
    index: int = 0
    message: OpenAIChoiceMessage
    finish_reason: Optional[str] = "stop"

class OpenAIUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

class OpenAIChatCompletionResponse(BaseModel):
    """OpenAI 标准非流式响应体"""
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: List[OpenAIChoice]
    usage: OpenAIUsage

def _to_internal_messages(openai_msgs: List[OpenAIChatMessage]) -> List[Message]:
    """将 OpenAI 格式消息转换为内部通用 Message 列表 (支持双向携带 tool_calls 与 tool_call_id)"""
    msgs: List[Message] = []
    for m in openai_msgs:
        internal_tc = None
        if m.tool_calls:
            internal_tc = []
            for tc in m.tool_calls:
                fn = tc.get("function") or {}
                raw_args = fn.get("arguments", "{}")
                if isinstance(raw_args, dict):
                    args_dict = raw_args
                    raw_args_str = json.dumps(raw_args, ensure_ascii=False)
                else:
                    raw_args_str = str(raw_args)
                    try:
                        args_dict = json.loads(raw_args_str)
                    except Exception:
                        args_dict = {}
                internal_tc.append(ToolCall(
                    id=tc.get("id", f"call_{uuid.uuid4().hex[:8]}"),
                    name=fn.get("name") or tc.get("name", ""),
                    arguments=args_dict,
                    raw_arguments=raw_args_str
                ))
        msgs.append(Message(
            role=m.role,
            content=m.content or "",
            tool_calls=internal_tc,
            tool_call_id=m.tool_call_id,
            name=m.name
        ))
    return msgs

def _to_internal_tools(openai_tools: Optional[List[Dict[str, Any]]]) -> Optional[List[ToolDefinition]]:
    """将 OpenAI 声明的 tools 格式映射为内部 ToolDefinition 列表"""
    if not openai_tools:
        return None
    tools: List[ToolDefinition] = []
    for t in openai_tools:
        fn = t.get("function") or t
        tools.append(ToolDefinition(
            name=fn.get("name", ""),
            description=fn.get("description", ""),
            parameters=fn.get("parameters") or {}
        ))
    return tools

def _resolve_provider_and_kwargs(req: OpenAIChatCompletionRequest) -> tuple[str, Dict[str, Any]]:
    """根据请求的模型名称智能分流到 key 驱动或 agt cli 驱动"""
    model_name = (req.model or "").strip()
    extra_kwargs: Dict[str, Any] = {}

    if req.temperature is not None:
        extra_kwargs["temperature"] = req.temperature

    provider_type, target_model = resolve_agt_model(model_name)
    effort_val = req.reasoning_effort or "medium"
    if str(effort_val).strip().lower() in ("", "off", "none"):
        effort_val = "medium"
    elif str(effort_val).strip().lower() not in ("low", "medium", "high"):
        effort_val = "medium"
    else:
        effort_val = str(effort_val).strip().lower()

    extra_kwargs["effort"] = effort_val
    extra_kwargs["reasoning_effort"] = effort_val

    if provider_type == "cli":
        extra_kwargs["executable"] = "agy"
        extra_kwargs["model"] = target_model
    else:
        extra_kwargs["model"] = target_model or ai_config.OPENAI_MODEL

    return provider_type, extra_kwargs

@openai_router.get("/v1/models")
@openai_router.get("/models")
async def list_models():
    """
    OpenAI 标准模型列表端点：
    完整挂载 agt-* Antigravity 系列模型矩阵与外部 API-Key 模型列表。
    """
    created_ts = int(time.time())
    available_models = [
        {"id": "agt-gemini-3.8-flash", "object": "model", "created": created_ts, "owned_by": "antigravity", "description": "Gemini 3.8 Flash High Fast"},
        {"id": "agt-gemini-3.7-flash", "object": "model", "created": created_ts, "owned_by": "antigravity", "description": "Gemini 3.7 Flash Medium Fast"},
        {"id": "agt-gemini-3.6-flash", "object": "model", "created": created_ts, "owned_by": "antigravity", "description": "Gemini 3.6 Flash Medium Fast"},
        {"id": "agt-gemini-3.1-pro", "object": "model", "created": created_ts, "owned_by": "antigravity", "description": "Gemini 3.1 Pro Low"},
        {"id": "agt-claude-sonnet-4.6", "object": "model", "created": created_ts, "owned_by": "antigravity", "description": "Claude Sonnet 4.6 (Thinking)"},
        {"id": "agt-claude-opus-4.6", "object": "model", "created": created_ts, "owned_by": "antigravity", "description": "Claude Opus 4.6 (Thinking)"},
        {"id": "agt-gpt-oss-120b", "object": "model", "created": created_ts, "owned_by": "antigravity", "description": "GPT-OSS 120B (Medium)"},
        {"id": "agy", "object": "model", "created": created_ts, "owned_by": "antigravity", "description": "Default AGY Model"},
        {"id": "gemini-flash-lite-latest", "object": "model", "created": created_ts, "owned_by": "openai-proxy"},
        {"id": "minimax/minimax-m3:free", "object": "model", "created": created_ts, "owned_by": "openai-proxy"}
    ]
    return {
        "object": "list",
        "data": available_models
    }

@openai_router.post("/v1/chat/completions")
@openai_router.post("/chat/completions")
async def chat_completions(req: OpenAIChatCompletionRequest):
    """
    OpenAI 标准对话补全端点：
    支持非流式 JSON 返回与 SSE 流式 Chunk 实时推送，自动路由底层模型驱动。
    """
    if not req.messages or len(req.messages) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OpenAI request must contain a non-empty 'messages' list."
        )

    internal_messages = _to_internal_messages(req.messages)
    internal_tools = _to_internal_tools(req.tools)
    provider_type, extra_kwargs = _resolve_provider_and_kwargs(req)

    completion_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    created_ts = int(time.time())

    # 1. 流式响应 (stream=True)
    if req.stream:
        async def openai_stream_generator() -> AsyncGenerator[Dict[str, Any], None]:
            try:
                # 首先发送起始 Chunk (声明角色)
                init_chunk = {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": created_ts,
                    "model": req.model,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"role": "assistant", "content": ""},
                            "finish_reason": None
                        }
                    ]
                }
                yield {"data": json.dumps(init_chunk, ensure_ascii=False)}

                # 逐块转发模型增量文本
                async for chunk in ai_orchestrator.generate_stream(
                    messages=internal_messages,
                    provider_type=provider_type,
                    tools=internal_tools,
                    **extra_kwargs
                ):
                    if chunk.delta:
                        stream_payload = {
                            "id": completion_id,
                            "object": "chat.completion.chunk",
                            "created": created_ts,
                            "model": req.model,
                            "choices": [
                                {
                                    "index": 0,
                                    "delta": {"content": chunk.delta},
                                    "finish_reason": None
                                }
                            ]
                        }
                        yield {"data": json.dumps(stream_payload, ensure_ascii=False)}

                # 发送结束标记 Chunk
                finish_payload = {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": created_ts,
                    "model": req.model,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {},
                            "finish_reason": "stop"
                        }
                    ]
                }
                yield {"data": json.dumps(finish_payload, ensure_ascii=False)}

                # 发送 OpenAI 协议终止标记
                yield {"data": "[DONE]"}
            except Exception as e:
                error_payload = {
                    "error": {
                        "message": str(e),
                        "type": "server_error",
                        "param": None,
                        "code": "model_stream_error"
                    }
                }
                yield {"data": json.dumps(error_payload, ensure_ascii=False)}
                yield {"data": "[DONE]"}

        return EventSourceResponse(openai_stream_generator())

    # 2. 非流式响应 (stream=False)
    try:
        response = await ai_orchestrator.generate(
            messages=internal_messages,
            provider_type=provider_type,
            tools=internal_tools,
            **extra_kwargs
        )

        content = response.content or ""
        out_tool_calls = None
        if response.tool_calls:
            out_tool_calls = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": tc.raw_arguments or json.dumps(tc.arguments, ensure_ascii=False)
                    }
                }
                for tc in response.tool_calls
            ]

        # 简单估算 Token 满足第三方客户端统计校验
        prompt_len = sum(len(m.content or "") for m in internal_messages)
        prompt_tokens = max(1, prompt_len // 4)
        completion_tokens = max(1, len(content) // 2)

        return OpenAIChatCompletionResponse(
            id=completion_id,
            created=created_ts,
            model=req.model,
            choices=[
                OpenAIChoice(
                    index=0,
                    message=OpenAIChoiceMessage(
                        role="assistant",
                        content=content,
                        tool_calls=out_tool_calls
                    ),
                    finish_reason="tool_calls" if out_tool_calls else (response.finish_reason or "stop")
                )
            ],
            usage=OpenAIUsage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens
            )
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"OpenAI completion generation failed: {str(e)}"
        )
