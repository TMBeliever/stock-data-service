import logging
from typing import Optional
from pydantic import BaseModel
import jwt
from fastapi import Request

from quant_agent.config import agent_config

logger = logging.getLogger(__name__)

class UserAuth(BaseModel):
    """用户认证与权限状态模型"""
    user_id: Optional[str] = None
    username: str = "guest"
    role: str = "guest"
    is_admin: bool = False

def decode_token(token: str) -> Optional[dict]:
    """解码校验 JWT Token"""
    try:
        payload = jwt.decode(
            token,
            agent_config.JWT_SECRET_KEY,
            algorithms=[agent_config.JWT_ALGORITHM]
        )
        return payload
    except jwt.PyJWTError as e:
        logger.debug("Failed to decode JWT token: %s", e)
        return None

async def get_current_auth(request: Request) -> UserAuth:
    """
    FastAPI 依赖注入：解析 Authorization 请求头中的 Bearer Token
    若未提供或 Token 非法，严格降级为普通访客权限 (is_admin=False)
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return UserAuth(
            user_id=None,
            username="guest",
            role="guest",
            is_admin=False
        )

    token = auth_header.split(" ", 1)[1].strip()
    payload = decode_token(token)
    if not payload:
        return UserAuth(
            user_id=None,
            username="guest",
            role="guest",
            is_admin=False
        )

    user_id = str(payload.get("sub", ""))
    username = str(payload.get("username", "unknown"))
    role = str(payload.get("role", "user"))
    is_admin = (role == "admin")

    return UserAuth(
        user_id=user_id,
        username=username,
        role=role,
        is_admin=is_admin
    )
