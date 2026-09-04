from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from common_server.database import get_db
from common_server.models import User
from common_server.security import decode_access_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)

async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db)
) -> User:
    """提取并校验 Bearer Token，返回已登录的 User 对象"""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials or token expired",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not token:
        raise credentials_exception

    payload = decode_access_token(token)
    if not payload:
        raise credentials_exception

    user_id_str = payload.get("sub")
    if not user_id_str:
        raise credentials_exception

    try:
        user_id = int(user_id_str)
    except ValueError:
        raise credentials_exception

    stmt = select(User).where(User.id == user_id)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or account disabled"
        )
    return user

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
