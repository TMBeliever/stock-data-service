from fastapi import Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from common_server.database import get_db
from common_server.models import User
from common_server.security import decode_access_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)

async def get_current_user(
    request: Request,
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db)
) -> User:
    """提取并校验 Bearer Token，返回已登录的 User 对象；支持内部智能体 (quant-agent) 互信互通"""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials or token expired",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if token:
        payload = decode_access_token(token)
        if payload:
            user_id_str = payload.get("sub")
            if user_id_str:
                try:
                    user_id = int(user_id_str)
                    stmt = select(User).where(User.id == user_id)
                    result = await db.execute(stmt)
                    user = result.scalar_one_or_none()
                    if user and user.is_active:
                        return user
                except ValueError:
                    pass

    # 若为 quant-agent 内部服务互信调用，优雅兜底关联至主活跃用户 (通常为管理员用户)
    if request.headers.get("X-Internal-Service") == "quant-agent" or request.headers.get("x-internal-service") == "quant-agent":
        stmt = select(User).where(User.is_active == True).order_by(User.id.asc()).limit(1)
        result = await db.execute(stmt)
        internal_user = result.scalar_one_or_none()
        if internal_user:
            return internal_user

    raise credentials_exception

async def require_vip(
    current_user: User = Depends(get_current_user)
) -> User:
    """VIP 权限守卫：若用户非有效 VIP 则直接拦截 403"""
    if not current_user.is_vip:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="VIP subscription required to access this feature"
        )
    return current_user

async def require_admin(
    current_user: User = Depends(get_current_user)
) -> User:
    """管理员权限守卫"""
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required"
        )
    return current_user
