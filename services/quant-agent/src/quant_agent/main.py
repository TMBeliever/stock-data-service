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
    agent_mode: Optional[str] = Field("auto", description="场景运行模式 ('auto' | 'quant' | 'devops' | 'all')")



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
    """获取已挂载 MCP 服务器状态与分层工具清单（包含各工具详细能力定义与独立开关状态）"""
    await quant_agent.initialize_tools()
    cfg = settings_manager.get_config()
    all_tools = quant_agent.tool_registry.list_tools()
    global_disabled = set(getattr(cfg, "disabled_tools", []) or [])

    servers_report = []
    for s in cfg.mcp_servers:
        # 绝不让旧版残留的 stock-data-mcp 出现在列表中
        if s.name == "stock-data-mcp":
            continue

        if s.name == "mcp-stock" or s.group in ("stock", "system"):
            matched = [
                t for t in all_tools
                if t.category in ("system", "quant", "stock")
                and t.name not in ("validate_strategy_code", "run_backtest_fast")
            ]
        elif s.name == "mcp-user" or s.group == "user":
            matched = [t for t in all_tools if t.category == "user"]
        else:
            matched = [t for t in all_tools if t.category == s.category]

        server_disabled = set(getattr(s, "disabled_tools", []) or [])
        matched_tools = [
            {
                "name": t.name,
                "description": t.description or t.name,
                "parameters": t.parameters,
                "category": t.category,
                "enabled": (t.name not in server_disabled) and (t.name not in global_disabled) and s.enabled
            }
            for t in matched
        ]

        active_count = sum(1 for t in matched_tools if t["enabled"])

        servers_report.append({
            "name": s.name,
            "type": s.type,
            "url": s.url,
            "command": s.command,
            "args": s.args,
            "cwd": s.cwd,
            "enabled": s.enabled,
            "group": s.group,
            "category": s.category,
            "description": s.description,
            "allow_user_toggle": s.allow_user_toggle,
            "disabled_tools": list(server_disabled),
            "status": "CONNECTED" if (s.enabled and len(matched_tools) > 0) else ("DISABLED" if not s.enabled else "DISCONNECTED"),
            "tools_count": len(matched_tools),
            "active_tools_count": active_count,
            "tools": matched_tools
        })

    # 如果是超级管理员，额外追加系统级运维/DevOps工具项
    if auth.is_admin:
        admin_tools = quant_agent._admin_tool_registry.list_tools()
        admin_enabled = getattr(cfg, "admin_tools_enabled", True)
        admin_matched = [
            {
                "name": t.name,
                "description": t.description or t.name,
                "parameters": t.parameters,
                "category": t.category,
                "enabled": (t.name not in global_disabled) and admin_enabled
            }
            for t in admin_tools
        ]
        servers_report.append({
            "name": "admin-system-tools",
            "type": "internal",
            "url": None,
            "command": None,
            "args": [],
            "cwd": None,
            "enabled": admin_enabled,
            "group": "admin",
            "category": "admin_devops",
            "description": "超级管理员专属系统级运维管理工具 (宿主机 Shell、源码修改、Docker治理、微服务运维)",
            "allow_user_toggle": True,
            "disabled_tools": [t.name for t in admin_tools if t.name in global_disabled],
            "status": "CONNECTED" if admin_enabled else "DISABLED",
            "tools_count": len(admin_matched),
            "active_tools_count": sum(1 for t in admin_matched if t["enabled"]),
            "tools": admin_matched
        })

    return {
        "status": "success",
        "total": len(servers_report),
        "servers": servers_report
    }

@app.post("/api/v1/agent/mcp/servers", tags=["MCP Management"])
async def save_mcp_server(server: McpServerConfig, auth: UserAuth = Depends(get_current_auth)):
    """添加或更新自定义 MCP Server"""
    # stdio 本地命令模式涉及服务器系统权限，需要超管；HTTP 远程网关模式允许普通用户配置个人 MCP
    if server.type == "stdio" and not auth.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="配置本地命令行 (stdio) MCP 服务需要超级管理员权限")

    cfg = settings_manager.get_config()
    existing = [s for s in cfg.mcp_servers if s.name != server.name and s.name != "stock-data-mcp"]
    existing.append(server)
    cfg = settings_manager.update_config({"mcp_servers": [s.model_dump() for s in existing]})
    await quant_agent.initialize_tools(force_refresh=True)
    return {
        "status": "success",
        "message": f"MCP 服务器 '{server.name}' 配置已保存",
        "servers": cfg.mcp_servers
    }

class ToggleMcpRequest(BaseModel):
    enabled: bool

@app.post("/api/v1/agent/mcp/servers/{server_name}/toggle", tags=["MCP Management"])
async def toggle_mcp_server(server_name: str, req: ToggleMcpRequest, auth: UserAuth = Depends(get_current_auth)):
    """动态热插拔 MCP 服务器 (支持用户自主启停其对应权限的 MCP，超管可控制系统级运维工具)"""
    # 处理超管系统级运维工具开关
    if server_name == "admin-system-tools":
        if not auth.is_admin:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="控制系统级运维工具调用需要超级管理员权限")
        settings_manager.update_config({"admin_tools_enabled": req.enabled})
        return {
            "status": "success",
            "message": f"系统级运维工具已{'成功授权开启' if req.enabled else '安全关闭屏蔽'}",
            "server": {
                "name": "admin-system-tools",
                "enabled": req.enabled,
                "group": "admin"
            },
            "enabled": req.enabled
        }

    cfg = settings_manager.get_config()
    target = None
    for s in cfg.mcp_servers:
        if s.name == server_name:
            target = s
            break
    if not target:
        raise HTTPException(status_code=404, detail=f"未找到 MCP 服务: '{server_name}'")

    # 权限检查：如果服务显式禁止用户开关且当前非超管，则拦截
    if not target.allow_user_toggle and not auth.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"MCP 服务 '{server_name}' 属于系统核心受控模块，仅允许超级管理员控制开关"
        )

    target.enabled = req.enabled
    settings_manager.update_config({"mcp_servers": [s.model_dump() for s in cfg.mcp_servers]})
    await quant_agent.initialize_tools(force_refresh=True)
    return {
        "status": "success",
        "message": f"MCP 服务 '{server_name}' 已{'成功启用挂载' if req.enabled else '安全断开挂起'}",
        "server": target.model_dump(),
        "enabled": target.enabled
    }

class ToggleToolRequest(BaseModel):
    enabled: bool
    server_name: Optional[str] = None

@app.post("/api/v1/agent/mcp/tools/{tool_name}/toggle", tags=["MCP Management"])
@app.post("/api/v1/agent/mcp/servers/{server_name}/tools/{tool_name}/toggle", tags=["MCP Management"])
async def toggle_tool_status(
    tool_name: str,
    req: ToggleToolRequest,
    server_name: Optional[str] = None,
    auth: UserAuth = Depends(get_current_auth)
):
    """开关单个具体工具的能力调用 (普通用户可控制 stock/user 等工具，超管可控制运维工具与全局工具)"""
    cfg = settings_manager.get_config()

    # 判定是否是超管运维工具
    admin_tool_names = {t.name for t in quant_agent._admin_tool_registry.list_tools()}
    if tool_name in admin_tool_names:
        if not auth.is_admin:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="控制系统级运维工具开关需要超级管理员权限")
        current_disabled = set(cfg.disabled_tools or [])
        if req.enabled:
            current_disabled.discard(tool_name)
        else:
            current_disabled.add(tool_name)
        settings_manager.update_config({"disabled_tools": list(current_disabled)})
        return {
            "status": "success",
            "message": f"系统级工具 '{tool_name}' 已{'成功启用' if req.enabled else '安全停用'}",
            "tool": tool_name,
            "enabled": req.enabled
        }

    # 查找该工具属于哪个 MCP 服务
    target_server = None
    target_server_name = server_name or req.server_name

    if target_server_name:
        for s in cfg.mcp_servers:
            if s.name == target_server_name:
                target_server = s
                break
    else:
        # 自动推断所属服务
        all_tools = quant_agent.tool_registry.list_tools()
        for t in all_tools:
            if t.name == tool_name:
                if t.category == "user":
                    target_server = next((s for s in cfg.mcp_servers if s.name == "mcp-user"), None)
                elif t.category in ("system", "quant", "stock"):
                    target_server = next((s for s in cfg.mcp_servers if s.name == "mcp-stock"), None)
                break

    if not target_server:
        # 未归属具体服务则写入全局禁用表
        current_disabled = set(cfg.disabled_tools or [])
        if req.enabled:
            current_disabled.discard(tool_name)
        else:
            current_disabled.add(tool_name)
        settings_manager.update_config({"disabled_tools": list(current_disabled)})
        return {
            "status": "success",
            "message": f"工具 '{tool_name}' 已{'成功启用' if req.enabled else '安全停用'}",
            "tool": tool_name,
            "enabled": req.enabled
        }

    # 权限检查
    if not target_server.allow_user_toggle and not auth.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="该服务禁止普通用户修改工具配置")

    # 更新 server 内部的 disabled_tools
    s_disabled = set(getattr(target_server, "disabled_tools", []) or [])
    if req.enabled:
        s_disabled.discard(tool_name)
    else:
        s_disabled.add(tool_name)
    target_server.disabled_tools = list(s_disabled)

    settings_manager.update_config({"mcp_servers": [s.model_dump() for s in cfg.mcp_servers]})
    return {
        "status": "success",
        "message": f"服务 [{target_server.name}] 下工具 '{tool_name}' 已{'成功启用' if req.enabled else '安全停用'}",
        "server": target_server.name,
        "tool": tool_name,
        "enabled": req.enabled
    }


@app.get("/api/v1/agent/tools", tags=["Tools"])
async def list_available_tools(
    scope: Optional[str] = Query(None, description="工具领域过滤 ('quant' | 'devops' | 'all')"),
    auth: UserAuth = Depends(get_current_auth)
):
    """获取智能体当前挂载的所有 MCP 与量化工具清单 (支持按 quant / devops / all 领域过滤)"""
    await quant_agent.initialize_tools()
    target_scope = scope if scope in ("quant", "devops", "all") else ("all" if auth.is_admin else "quant")
    reg = quant_agent.get_active_tool_registry(is_admin=auth.is_admin, scope=target_scope)
    defs = reg.to_definitions()
    return {
        "is_admin": auth.is_admin,
        "role": auth.role,
        "scope": target_scope,
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
        model=req.model or cfg.default_model or "agt-gemini-3.8-flash",
        provider=req.provider,  # 标准 OpenAI 网关通过 model 自动分流，无需外部写死
        system_prompt=req.system_prompt,
        page_context=page_ctx,
        temperature=temp,
        is_admin=auth.is_admin,
        agent_mode=req.agent_mode or "auto",
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
