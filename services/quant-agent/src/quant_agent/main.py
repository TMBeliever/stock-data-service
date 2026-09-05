import json
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException, status, Depends, UploadFile, File, Form, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from ai_core.models import Message
from quant_agent.config import agent_config
from quant_agent.agent_engine import quant_agent
from quant_agent.auth import UserAuth, get_current_auth
from quant_agent.settings import settings_manager, AgentRuntimeConfig, McpServerConfig
from quant_agent.admin_tools import current_active_project_dir, current_sticky_cwd

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

from quant_agent.project_manager import project_manager

class CreateProjectRequest(BaseModel):
    """创建工程项目请求体 (支持本地机器与部署机器上的项目)"""
    name: str = Field(..., description="项目名称，如 quant-system, hy-h5-api")
    host_type: str = Field("local", description="运行环境类型: 'local' (本地机器) 或 'remote' (部署机器)")
    path: str = Field(..., description="项目在对应机器上的根目录路径")
    machine_name: Optional[str] = Field("", description="机器显示名称，如 Ubuntu测试机")
    machine_address: Optional[str] = Field("", description="部署机器IP或域名，如 192.168.1.100")
    description: Optional[str] = Field("", description="项目简要说明")

class CreateSessionRequest(BaseModel):
    """创建会话请求体"""
    title: Optional[str] = Field("新对话", description="会话标题")

class SaveMessageRequest(BaseModel):
    """保存会话消息请求体"""
    role: str
    content: str
    id: Optional[str] = None
    cards: Optional[List[Dict[str, Any]]] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None

class UpdateConfigRequest(BaseModel):
    """更新全局运行配置请求体"""
    execution_mode: Optional[str] = None
    default_model: Optional[str] = None
    temperature: Optional[float] = None
    max_steps: Optional[int] = None
    max_observation_chars: Optional[int] = None

class AgentChatRequest(BaseModel):
    """智能体多端通用对话请求体"""
    prompt: Optional[str] = Field(None, description="输入提示词")
    messages: Optional[List[Message]] = Field(None, description="标准多轮历史消息 (若提供则优先)")
    system_prompt: Optional[str] = Field(None, description="可选覆盖系统提示词")
    page_context: Optional[str] = Field("", description="调用来源前端情境 (如 'strategy' 或 'market')")
    model: Optional[str] = Field(None, description="指定模型名称 (如 gemini-3.7-flash)")
    provider: Optional[str] = Field(None, description="底层驱动类型 ('key' 或 'cli')")
    temperature: Optional[float] = Field(None, ge=0.0, le=2.0, description="采样随机度")
    thinking_level: Optional[str] = Field("medium", description="思考程度 ('off' | 'low' | 'medium' | 'high')")
    project_id: Optional[str] = Field(None, description="所属项目 ID")
    project_path: Optional[str] = Field(None, description="项目物理根目录路径")
    host_type: Optional[str] = Field(None, description="项目所在主机类型 ('local' | 'remote')")
    execution_mode: Optional[str] = Field(None, description="执行安全模式 ('auto' | 'confirm_sensitive' | 'confirm_all')")
    approved_tool_calls: Optional[List[str]] = Field(default_factory=list, description="用户已显式授权的 tool_call_id 列表")
    approved_tool_call: Optional[Dict[str, Any]] = Field(None, description="用户已授权立即执行的工具调用对象 {'id': ..., 'name': ..., 'arguments': ...}")
    max_steps: Optional[int] = Field(None, description="单次最大步数 (None 或 0 为无限制，对标 DSH)")



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

@app.get("/api/v1/agent/config", tags=["Configuration"])
async def get_agent_config(auth: UserAuth = Depends(get_current_auth)):
    """获取当前 Agent 全局安全与运行配置"""
    cfg = settings_manager.get_config()
    return {
        "status": "success",
        "config": cfg.model_dump(),
        "is_admin": auth.is_admin
    }

@app.post("/api/v1/agent/config", tags=["Configuration"])
async def update_agent_config(req: UpdateConfigRequest, auth: UserAuth = Depends(get_current_auth)):
    """更新 Agent 全局安全与运行配置"""
    if not auth.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="修改智能体全局安全配置需要超级管理员权限 (Super Admin required)")
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    cfg = settings_manager.update_config(updates)
    return {
        "status": "success",
        "message": "Agent 配置已保存并实时生效",
        "config": cfg.model_dump()
    }

@app.get("/api/v1/agent/mcp/servers", tags=["MCP Management"])
async def list_mcp_servers(auth: UserAuth = Depends(get_current_auth)):
    """获取已挂载 MCP 服务器状态与工具清单"""
    await quant_agent.initialize_tools()
    cfg = settings_manager.get_config()
    quant_tools = quant_agent.tool_registry.list_tools()

    servers_report = []
    for s in cfg.mcp_servers:
        is_stock_data = "stock-data" in s.name
        matched_tools = [
            {
                "name": t.name,
                "description": t.description.split("\n")[0] if t.description else t.name,
                "category": t.category
            }
            for t in quant_tools
            if t.category == s.category or (is_stock_data and t.category == "quant")
        ]
        servers_report.append({
            "name": s.name,
            "command": s.command,
            "args": s.args,
            "cwd": s.cwd,
            "enabled": s.enabled,
            "category": s.category,
            "description": s.description,
            "status": "CONNECTED" if (s.enabled and len(matched_tools) > 0) else "CONFIGURED",
            "tools_count": len(matched_tools),
            "tools": matched_tools
        })

    return {
        "status": "success",
        "total": len(servers_report),
        "servers": servers_report
    }

@app.post("/api/v1/agent/mcp/servers", tags=["MCP Management"])
async def save_mcp_server(server: McpServerConfig, auth: UserAuth = Depends(get_current_auth)):
    """添加或更新自定义 MCP Server"""
    if not auth.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="配置与挂载 MCP 服务需要超级管理员权限 (Super Admin required)")
    cfg = settings_manager.get_config()
    existing = [s for s in cfg.mcp_servers if s.name != server.name]
    existing.append(server)
    cfg = settings_manager.update_config({"mcp_servers": [s.model_dump() for s in existing]})
    return {
        "status": "success",
        "message": f"MCP 服务器 '{server.name}' 配置已保存",
        "servers": cfg.mcp_servers
    }

class ToggleMcpRequest(BaseModel):
    enabled: bool

@app.post("/api/v1/agent/mcp/servers/{server_name}/toggle", tags=["MCP Management"])
async def toggle_mcp_server(server_name: str, req: ToggleMcpRequest, auth: UserAuth = Depends(get_current_auth)):
    """动态热插拔 MCP 服务器 (启用或挂起断开)"""
    if not auth.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="启停 MCP 服务需要超级管理员权限 (Super Admin required)")
    cfg = settings_manager.get_config()
    target = None
    for s in cfg.mcp_servers:
        if s.name == server_name:
            s.enabled = req.enabled
            target = s
            break
    if not target:
        raise HTTPException(status_code=404, detail="未找到该 MCP 服务器")
    
    settings_manager.update_config({"mcp_servers": [s.model_dump() for s in cfg.mcp_servers]})
    await quant_agent.initialize_tools(force_refresh=True)
    return {
        "status": "success",
        "message": f"MCP 服务 '{server_name}' 已{'启用挂载' if req.enabled else '安全断开'}",
        "server": target.model_dump()
    }


@app.get("/api/v1/agent/tools", tags=["Tools"])
async def list_available_tools(auth: UserAuth = Depends(get_current_auth)):
    """获取智能体当前挂载的所有 MCP 与量化工具清单 (依据权限动态判定)"""
    await quant_agent.initialize_tools()
    reg = quant_agent.get_active_tool_registry(is_admin=auth.is_admin)
    defs = reg.to_definitions()
    return {
        "is_admin": auth.is_admin,
        "role": auth.role,
        "total": len(defs),
        "tools": [t.to_openai_dict() for t in defs]
    }

@app.get("/api/v1/agent/projects", tags=["Codex Workspace"])
async def list_projects(auth: UserAuth = Depends(get_current_auth)):
    """获取所有挂载的工程项目与会话树 (支持本地与部署机器)"""
    projs = project_manager.list_projects()
    return {
        "status": "success",
        "total": len(projs),
        "projects": [p.model_dump() for p in projs]
    }

@app.post("/api/v1/agent/projects", tags=["Codex Workspace"])
async def create_project(req: CreateProjectRequest, auth: UserAuth = Depends(get_current_auth)):
    """挂载新工程项目 (支持本地机器与部署机器上的项目)"""
    new_p = project_manager.create_project(
        name=req.name,
        host_type=req.host_type,
        path=req.path,
        machine_name=req.machine_name or "",
        machine_address=req.machine_address or "",
        description=req.description or ""
    )
    return {
        "status": "success",
        "message": f"项目 '{new_p.name}' 挂载成功",
        "project": new_p.model_dump()
    }

@app.delete("/api/v1/agent/projects/{project_id}", tags=["Codex Workspace"])
async def delete_project(project_id: str, auth: UserAuth = Depends(get_current_auth)):
    """移除挂载的工程项目"""
    if not auth.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="移除挂载工程需要超级管理员权限 (Super Admin required)")
    ok = project_manager.delete_project(project_id)
    if not ok:
        raise HTTPException(status_code=404, detail="项目不存在")
    return {"status": "success", "message": "项目已成功移除"}

@app.get("/api/v1/agent/fs/discover", tags=["Codex Workspace"])
async def discover_projects(auth: UserAuth = Depends(get_current_auth)):
    """在部署机/服务端全自动探测可用的量化与代码工程 (无需用户知晓或手输路径)"""
    projects = project_manager.discover_projects_on_system()
    return {
        "status": "success",
        "total": len(projects),
        "projects": projects
    }

@app.get("/api/v1/agent/fs/list", tags=["Codex Workspace"])
async def list_filesystem_directory(
    path: Optional[str] = Query(None, description="目标目录路径，留空默认根目录或Home"),
    show_hidden: bool = Query(False, description="是否显示隐藏文件/文件夹"),
    auth: UserAuth = Depends(get_current_auth)
):
    """浏览部署服务器/宿主机上的文件目录树 (方案 A：远程项目挂载)"""
    res = project_manager.list_filesystem_directory(target_path=path, show_hidden=show_hidden)
    return {
        "status": "success",
        "data": res
    }

@app.post("/api/v1/agent/fs/upload", tags=["Codex Workspace"])
async def upload_client_project(
    project_name: str = Form(..., description="项目名称"),
    destination_dir: Optional[str] = Form(None, description="部署机存放目标路径"),
    host_type: str = Form("remote", description="'remote' (部署机) 或 'local'"),
    machine_name: Optional[str] = Form("", description="部署机器名称"),
    relative_paths: Optional[str] = Form(None, description="文件相对路径 JSON 列表"),
    files: List[UploadFile] = File(..., description="上传的文件列表"),
    auth: UserAuth = Depends(get_current_auth)
):
    """从访问机客户端上传项目文件/文件夹至部署机并自动注册挂载为项目"""
    rel_list = []
    if relative_paths:
        try:
            rel_list = json.loads(relative_paths)
        except Exception:
            rel_list = []

    files_data = []
    zip_bytes = None

    for i, f in enumerate(files):
        content = await f.read()
        if len(files) == 1 and f.filename and f.filename.lower().endswith(".zip"):
            zip_bytes = content
            break
        rel_p = rel_list[i] if i < len(rel_list) and rel_list[i] else f.filename or f"file_{i}"
        files_data.append((rel_p, content))

    new_p = project_manager.import_uploaded_project(
        project_name=project_name,
        destination_dir=destination_dir,
        host_type=host_type,
        machine_name=machine_name or "当前部署机节点 (Ubuntu/Linux)",
        files_data=files_data if not zip_bytes else None,
        zip_bytes=zip_bytes
    )

    return {
        "status": "success",
        "message": f"项目 '{new_p.name}' 已成功上传并挂载至部署机",
        "project": new_p.model_dump()
    }

@app.post("/api/v1/agent/projects/{project_id}/sessions", tags=["Codex Workspace"])
async def create_project_session(project_id: str, req: CreateSessionRequest, auth: UserAuth = Depends(get_current_auth)):
    """在指定工程下新建任务会话"""
    sess = project_manager.create_session(project_id, title=req.title or "新对话")
    if not sess:
        raise HTTPException(status_code=404, detail="项目不存在")
    return {
        "status": "success",
        "session": sess.model_dump()
    }

@app.delete("/api/v1/agent/projects/{project_id}/sessions/{session_id}", tags=["Codex Workspace"])
async def delete_project_session(project_id: str, session_id: str, auth: UserAuth = Depends(get_current_auth)):
    """删除指定会话"""
    ok = project_manager.delete_session(project_id, session_id)
    if not ok:
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"status": "success", "message": "会话已删除"}

@app.post("/api/v1/agent/projects/{project_id}/sessions/{session_id}/messages", tags=["Codex Workspace"])
async def save_session_message(project_id: str, session_id: str, req: SaveMessageRequest, auth: UserAuth = Depends(get_current_auth)):
    """保存或追加对话消息至持久化项目历史"""
    msg = project_manager.add_message_to_session(
        project_id=project_id,
        session_id=session_id,
        role=req.role,
        content=req.content,
        cards=req.cards,
        tool_calls=req.tool_calls,
        message_id=req.id
    )
    if not msg:
        raise HTTPException(status_code=404, detail="会话或项目不存在")
    return {"status": "success", "message": msg.model_dump()}

@app.post("/api/v1/agent/chat", tags=["Agent Chat"])

async def chat_stream(req: AgentChatRequest, auth: UserAuth = Depends(get_current_auth)):
    """
    通用智能体流式对话接口 (SSE):
    实时分发推演事件 (thought, tool_call, tool_result, message, done)。
    当超管调用时，自动赋能全栈运维与控制能力。
    """
    messages = _resolve_messages(req)
    
    page_ctx = req.page_context or ""
    if req.project_path:
        current_active_project_dir.set(req.project_path)
        current_sticky_cwd.set(req.project_path)
        page_ctx = f"当前激活工程: [{req.project_id or '未命名'}] | 运行主机: {req.host_type or 'local'} | 物理工作目录: {req.project_path}\n{page_ctx}"
    else:
        current_active_project_dir.set(None)
        current_sticky_cwd.set(None)

    cfg = settings_manager.get_config()
    exec_mode = req.execution_mode or cfg.execution_mode or "auto"

    thinking_lvl = req.thinking_level or "medium"
    temp_map = {"off": 0.1, "low": 0.2, "medium": 0.3, "high": 0.4}
    temp = req.temperature if req.temperature is not None else temp_map.get(thinking_lvl, 0.2)

    stream = quant_agent.chat_stream(
        messages=messages,
        model=req.model or cfg.default_model or "minimax/minimax-m3:free",
        provider=req.provider or "key",
        system_prompt=req.system_prompt,
        page_context=page_ctx,
        temperature=temp,
        is_admin=auth.is_admin,
        execution_mode=exec_mode,
        sensitive_tools=cfg.sensitive_tools,
        approved_tool_calls=req.approved_tool_calls or [],
        approved_tool_call=req.approved_tool_call,
        thinking_level=thinking_lvl,
        max_steps=req.max_steps if req.max_steps is not None else cfg.max_steps
    )

    return EventSourceResponse(stream)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("quant_agent.main:app", host=agent_config.HOST, port=agent_config.PORT, reload=True)
