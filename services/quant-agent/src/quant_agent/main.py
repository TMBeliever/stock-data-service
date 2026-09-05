import json
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from ai_core.models import Message
from quant_agent.config import agent_config
from quant_agent.agent_engine import quant_agent

app = FastAPI(
    title="Quant Agent Service",
    description="Universal Financial Quant Agent Orchestration Service with MCP Tool Calling & Streaming ReAct",
    version="0.1.0"
)

# 允许跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class AgentChatRequest(BaseModel):
    """智能体多端通用对话请求体"""
    prompt: Optional[str] = Field(None, description="输入提示词")
    messages: Optional[List[Message]] = Field(None, description="标准多轮历史消息 (若提供则优先)")
    system_prompt: Optional[str] = Field(None, description="可选覆盖系统提示词")
    page_context: Optional[str] = Field("", description="调用来源前端情境 (如 'strategy' 或 'market')")
    model: Optional[str] = Field(None, description="指定模型名称 (如 gemini-flash-lite-latest 或 claude)")
    provider: Optional[str] = Field(None, description="底层驱动类型 ('key' 或 'cli')")
    temperature: Optional[float] = Field(0.2, ge=0.0, le=2.0, description="采样随机度")

def _resolve_messages(req: AgentChatRequest) -> List[Message]:
    """解析请求中的消息列表"""
    if req.messages and len(req.messages) > 0:
        return req.messages
    if req.prompt:
        return [Message.user(req.prompt)]
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="必须提供 'prompt' 或非空的 'messages' 列表。"
    )

@app.get("/health", tags=["System"])
async def health_check():
    """服务健康探针"""
    return {
        "status": "healthy",
        "service": "quant-agent",
        "port": agent_config.PORT,
        "ai_core_url": agent_config.AI_CORE_URL,
        "stock_data_dir": agent_config.STOCK_DATA_DIR
    }

@app.get("/api/v1/agent/tools", tags=["Tools"])
async def list_available_tools():
    """获取智能体当前挂载的所有 MCP 与量化工具清单"""
    await quant_agent.initialize_tools()
    defs = quant_agent.tool_registry.to_definitions()
    return {
        "total": len(defs),
        "tools": [t.to_openai_dict() for t in defs]
    }

@app.post("/api/v1/agent/chat", tags=["Agent Chat"])
async def chat_stream(req: AgentChatRequest):
    """
    通用智能体流式对话接口 (SSE):
    实时分发推演事件 (tool_call, tool_result, message, done)。
    可供 Web 前端、命令行 CLI、飞书/Telegram 机器人或任何外部客户端调用。
    """
    messages = _resolve_messages(req)
    
    stream = quant_agent.chat_stream(
        messages=messages,
        model=req.model,
        provider=req.provider,
        system_prompt=req.system_prompt,
        page_context=req.page_context or "",
        temperature=req.temperature or 0.2
    )

    return EventSourceResponse(stream)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("quant_agent.main:app", host=agent_config.HOST, port=agent_config.PORT, reload=True)
