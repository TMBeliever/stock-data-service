import datetime
from typing import Optional, Any
from pydantic import BaseModel, Field, ConfigDict

class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=32, description="用户名 (3~32 位字符)")
    password: str = Field(..., min_length=6, max_length=64, description="密码 (至少 6 位)")
    email: Optional[str] = Field(default=None, description="电子邮箱 (可选)")

class LoginRequest(BaseModel):
    username: str = Field(..., description="用户名")
    password: str = Field(..., description="密码")

class UserResponse(BaseModel):
    id: int
    username: str
    email: Optional[str] = None
    role: str
    is_active: bool
    is_vip: bool
    vip_expire_at: Optional[datetime.datetime] = None
    created_at: datetime.datetime

    model_config = ConfigDict(from_attributes=True)

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse

class GrantVipRequest(BaseModel):
    username: str = Field(..., description="目标赋权用户名")
    days: int = Field(default=30, ge=1, le=3650, description="开通/延期天数")

class MessageResponse(BaseModel):
    success: bool = True
    message: str
    data: Optional[Any] = None
