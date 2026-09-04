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
