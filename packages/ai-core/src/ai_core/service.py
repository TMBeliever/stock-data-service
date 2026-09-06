import json
from contextlib import asynccontextmanager
from typing import Optional, List, Dict, Any, AsyncGenerator
from fastapi import FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from ai_core.config import ai_config
from ai_core.models import Message, AIResponse, ToolDefinition
from ai_core.orchestrator import ai_orchestrator
from ai_core.openai_api import openai_router
from ai_core.anthropic_api import anthropic_router
from ai_core.process_pool import prewarmed_process_pool

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理：启动独占预热待命池巡检，退出时全量释放所有进程资源"""
    prewarmed_process_pool.start()
    yield
    await prewarmed_process_pool.shutdown()

app = FastAPI(
    title="AI Core Service",
    description="Universal AI Foundation Microservice supporting API Key & CLI Process drivers with Streaming SSE",
    version="0.1.0",
    lifespan=lifespan
)

# 挂载 OpenAI 标准兼容路由 (/v1/chat/completions, /v1/models 等)
app.include_router(openai_router)

# 挂载 Anthropic Messages 标准兼容路由 (/v1/messages, /messages 等，供 Claude CLI 使用)
app.include_router(anthropic_router)

# 允许跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class GenerateRequest(BaseModel):
    """文本与对话生成请求体"""
    prompt: Optional[str] = Field(None, description="简单输入提示词")
    system_prompt: Optional[str] = Field(None, description="系统提示词设定")
    messages: Optional[List[Message]] = Field(None, description="标准多轮消息列表 (若提供则优先于 prompt)")
    tools: Optional[List[ToolDefinition]] = Field(None, description="可选模型挂载工具定义列表")
    provider: Optional[str] = Field(None, description="驱动类型: 'key' 或 'cli' (默认从配置自动读取)")
    model: Optional[str] = Field(None, description="指定模型名称 (仅适用于 key 驱动)")
    temperature: Optional[float] = Field(None, ge=0.0, le=2.0, description="采样随机度")
    cli_executable: Optional[str] = Field(None, description="CLI 执行程序名称或绝对路径 (例如 'agy', 'claude', '/usr/local/bin/agy')")
    cli_args: Optional[List[str]] = Field(None, description="CLI 参数模板列表 (例如 ['-p', '{prompt}', '--dangerously-skip-permissions'])")
    session_id: Optional[str] = Field(None, description="会话标识符 (用于绑定专属温备 Worker)")

def _resolve_messages(req: GenerateRequest) -> List[Message]:
    """解析请求中的消息列表"""
    if req.messages and len(req.messages) > 0:
        return req.messages
    if req.prompt:
        msgs: List[Message] = []
        if req.system_prompt:
            msgs.append(Message.system(req.system_prompt))
        msgs.append(Message.user(req.prompt))
        return msgs
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="必须提供 'prompt' 或非空的 'messages' 列表。"
    )

@app.get("/health", tags=["System"])
async def health_check():
    """服务健康探针"""
    return {
        "status": "healthy",
        "service": "ai-core",
        "default_provider": ai_config.DEFAULT_PROVIDER,
        "default_model": ai_config.OPENAI_MODEL,
        "base_url": ai_config.OPENAI_BASE_URL,
        "cli_executable": ai_config.CLI_EXECUTABLE,
    }

@app.get("/", tags=["System"])
async def root():
    return {
        "message": "Welcome to AI Core Service API",
        "docs_url": "/docs",
        "health_url": "/health"
    }

@app.get("/v1/pool/status", tags=["System"])
async def pool_status():
    """预热进程池实时状态诊断：查看待命/活跃 Worker 数量与池子健康状态"""
    pool = prewarmed_process_pool
    standby_count = pool._standby_queue.qsize()
    active_count = len(pool._active_processes)
    return {
        "pool_is_active": pool._is_active,
        "standby_ready": standby_count,
        "standby_pool_size": ai_config.CLI_STANDBY_POOL_SIZE,
        "active_in_use": active_count,
        "max_concurrency": ai_config.CLI_MAX_CONCURRENCY,
        "fill_task_running": pool._fill_task is not None and not pool._fill_task.done(),
        "sweeper_running": pool._sweeper_task is not None and not pool._sweeper_task.done(),
        "spawn_stagger_delay_s": ai_config.CLI_SPAWN_STAGGER_DELAY,
        "idle_timeout_s": ai_config.CLI_POOL_IDLE_TIMEOUT,
    }

@app.post("/api/v1/ai/generate", response_model=AIResponse, tags=["AI Generation"])
async def generate_completion(req: GenerateRequest):
    """单次生成：等待完整大模型输出并返回结构化响应"""
    messages = _resolve_messages(req)
    extra_kwargs = {}
    if req.model:
        extra_kwargs["model"] = req.model
    if req.temperature is not None:
        extra_kwargs["temperature"] = req.temperature
    if req.cli_executable:
        extra_kwargs["executable"] = req.cli_executable
    if req.cli_args:
        extra_kwargs["args_template"] = req.cli_args
    if req.session_id:
        extra_kwargs["session_id"] = req.session_id

    try:
        response = await ai_orchestrator.generate(
            messages=messages,
            provider_type=req.provider,
            tools=req.tools,
            **extra_kwargs
        )
        return response
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"AI 生成失败: {str(e)}"
        )

@app.post("/api/v1/ai/stream", tags=["AI Generation"])
async def stream_completion_post(req: GenerateRequest):
    """流式生成 (POST)：通过 SSE (Server-Sent Events) 逐 Token 推送增量分片"""
    messages = _resolve_messages(req)
    extra_kwargs = {}
    if req.model:
        extra_kwargs["model"] = req.model
    if req.temperature is not None:
        extra_kwargs["temperature"] = req.temperature
    if req.cli_executable:
        extra_kwargs["executable"] = req.cli_executable
    if req.cli_args:
        extra_kwargs["args_template"] = req.cli_args
    if req.session_id:
        extra_kwargs["session_id"] = req.session_id

    async def event_generator() -> AsyncGenerator[Dict[str, Any], None]:
        try:
            async for chunk in ai_orchestrator.generate_stream(
                messages=messages,
                provider_type=req.provider,
                tools=req.tools,
                **extra_kwargs
            ):
                payload: Dict[str, Any] = {
                    "delta": chunk.delta,
                    "role": chunk.role,
                    "finish_reason": chunk.finish_reason
                }
                if chunk.tool_calls:
                    payload["tool_calls"] = [tc.model_dump() for tc in chunk.tool_calls]
                yield {"event": "message", "data": json.dumps(payload, ensure_ascii=False)}
        except Exception as e:
            yield {"event": "error", "data": json.dumps({"error": str(e)}, ensure_ascii=False)}

    return EventSourceResponse(event_generator())

@app.get("/api/v1/ai/stream", tags=["AI Generation"])
async def stream_completion_get(
    prompt: str = Query(..., description="输入提示词"),
    system_prompt: Optional[str] = Query(None, description="系统提示词"),
    provider: Optional[str] = Query(None, description="驱动类型 ('key' 或 'cli')"),
    model: Optional[str] = Query(None, description="模型名称"),
    cli_executable: Optional[str] = Query(None, description="CLI 执行程序名称或绝对路径 (如 'agy')"),
    session_id: Optional[str] = Query(None, description="会话标识符 (可选)")
):
    """流式生成 (GET 快捷测试)：直接在浏览器或 EventSource 客户端调用的 SSE 端点"""
    req = GenerateRequest(
        prompt=prompt,
        system_prompt=system_prompt,
        provider=provider,
        model=model,
        cli_executable=cli_executable,
        session_id=session_id
    )
    return await stream_completion_post(req)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("ai_core.service:app", host="0.0.0.0", port=8070, reload=True)
