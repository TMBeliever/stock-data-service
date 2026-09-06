from typing import Optional, List, Dict, Any, Literal
from pydantic import BaseModel, Field

RoleType = Literal["system", "user", "assistant", "tool"]

class ToolCall(BaseModel):
    """大模型发起的工具调用声明"""
    id: str
    name: str
    arguments: Dict[str, Any] = Field(default_factory=dict)
    raw_arguments: Optional[str] = None

class ToolDefinition(BaseModel):
    """工具/函数声明元数据 (遵循 JSON Schema 标准)"""
    name: str
    description: str
    parameters: Dict[str, Any] = Field(default_factory=dict)

    def to_openai_dict(self) -> Dict[str, Any]:
        """转换为 OpenAI 兼容工具定义格式"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters
            }
        }

class Message(BaseModel):
    """标准对话消息"""
    role: RoleType
    content: Optional[str] = None
    tool_calls: Optional[List[ToolCall]] = None
    tool_call_id: Optional[str] = None
    name: Optional[str] = None

    @classmethod
    def system(cls, content: str) -> "Message":
        return cls(role="system", content=content)

    @classmethod
    def user(cls, content: str) -> "Message":
        return cls(role="user", content=content)

    @classmethod
    def assistant(cls, content: Optional[str] = None, tool_calls: Optional[List[ToolCall]] = None) -> "Message":
        return cls(role="assistant", content=content, tool_calls=tool_calls)

    @classmethod
    def tool_result(cls, tool_call_id: str, content: str, name: Optional[str] = None) -> "Message":
        return cls(role="tool", content=content, tool_call_id=tool_call_id, name=name)

class UsageInfo(BaseModel):
    """Token 消耗统计"""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

class StreamChunk(BaseModel):
    """流式返回的分片 (逐 Token 增量)"""
    delta: str = ""
    role: Optional[str] = None
    finish_reason: Optional[str] = None
    tool_calls: Optional[List[ToolCall]] = None
    usage: Optional[UsageInfo] = None
    raw_data: Optional[Dict[str, Any]] = None

class AIResponse(BaseModel):
    """完整生成的模型响应"""
    content: str = ""
    model: str = ""
    provider_type: Literal["key", "cli"]
    tool_calls: Optional[List[ToolCall]] = None
    usage: Optional[UsageInfo] = None
    finish_reason: Optional[str] = None
    raw_response: Optional[Dict[str, Any]] = None

# =========================================================================
# Antigravity 宿主机模型矩阵映射与路由解析
# =========================================================================

AGT_MODEL_MAP: Dict[str, str] = {
    # Gemini 官方家族
    "agt-gemini-3.8-flash": "gemini-3.8-flash",
    "agt-flash": "gemini-3.8-flash",
    "agt-gemini-3.7-flash": "gemini-3.7-flash",
    "agt-gemini-3.6-flash": "gemini-3.6-flash",
    "agt-gemini-3.1-pro": "gemini-3.1-pro",
    "agt-pro": "gemini-3.1-pro",
    # Claude 官方家族 (Antigravity 宿主机支持)
    "agt-claude-sonnet-4.6": "claude-sonnet-4.6",
    "agt-sonnet": "claude-sonnet-4.6",
    "agt-claude-opus-4.6": "claude-opus-4.6",
    "agt-opus": "claude-opus-4.6",
    # 开源大模型基座
    "agt-gpt-oss-120b": "gpt-oss-120b",
}

DEFAULT_AGT_MODEL = "gemini-3.8-flash"

def resolve_agt_model(model_name: Optional[str]) -> tuple[str, Optional[str]]:
    """
    智能模型路由器：
    返回 (provider_type, target_model)
    1. 若以 'agt-' 开头，精确命中 Antigravity 模型矩阵，返回 ('cli', 映射后真实模型名)；
    2. 若包含 'agy', 'cli', 'antigravity'，返回 ('cli', 'gemini-3.8-flash')；
    3. 若包含 'claude' (如 Claude CLI 原生请求的 claude-3-5-sonnet, claude-3-7-sonnet)，
       自动对齐到 Antigravity 对应的最强模型 ('cli', 'claude-sonnet-4.6')；
    4. 其余指定外部 key 的模型 (如 minimax/minimax-m3:free, gemini-flash-lite-latest, gpt-4o 等)，
       返回 ('key', 原始模型名)。
    """
    name = (model_name or "").strip()
    name_lower = name.lower()

    if not name:
        return "cli", DEFAULT_AGT_MODEL

    if name_lower in AGT_MODEL_MAP:
        return "cli", AGT_MODEL_MAP[name_lower]

    if name_lower.startswith("agt-"):
        sub_name = name[4:].strip()
        return "cli", AGT_MODEL_MAP.get(name_lower, sub_name or DEFAULT_AGT_MODEL)

    if "agy" in name_lower or "cli" in name_lower or "antigravity" in name_lower:
        return "cli", DEFAULT_AGT_MODEL

    if "claude" in name_lower:
        if "opus" in name_lower:
            return "cli", "claude-opus-4.6"
        return "cli", "claude-sonnet-4.6"

    # 其他外部模型路由至 Key Provider
    return "key", name

