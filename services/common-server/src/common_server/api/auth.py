import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from common_server.database import get_db
from common_server.models import User
from common_server.schemas import (
    RegisterRequest, LoginRequest, UserResponse, TokenResponse, GrantVipRequest, MessageResponse
)
from common_server.security import get_password_hash, verify_password, create_access_token
from common_server.dependencies import get_current_user, require_vip

router = APIRouter(prefix="/auth", tags=["Authentication"])

@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(req: RegisterRequest, db: AsyncSession = Depends(get_db)):
    """用户注册：验证唯一性并以 Bcrypt 加密入库"""
    # 1. 校验用户名唯一
    stmt_uname = select(User).where(User.username == req.username)
    res_uname = await db.execute(stmt_uname)
    if res_uname.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Username '{req.username}' is already registered."
        )

    # 2. 校验邮箱唯一 (若提供)
    if req.email:
        stmt_email = select(User).where(User.email == req.email)
        res_email = await db.execute(stmt_email)
        if res_email.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Email '{req.email}' is already registered."
            )

    # 3. 统计是否首位用户 (首位注册者自动赋予 admin 超管角色)
    stmt_count = select(func.count(User.id))
    total_users = (await db.execute(stmt_count)).scalar() or 0
    assigned_role = "admin" if total_users == 0 else "user"

    # 4. 创建新用户
    hashed_pwd = get_password_hash(req.password)
    user = User(
        username=req.username,
        email=req.email,
        hashed_password=hashed_pwd,
        role=assigned_role,
        is_active=True
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    return user

@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    """用户登录：密码核验并颁发标准 JWT Access Token"""
    stmt = select(User).where(User.username == req.username)
    res = await db.execute(stmt)
    user = res.scalar_one_or_none()

    if not user or not verify_password(req.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account has been disabled"
        )

    access_token = create_access_token(
        data={"sub": str(user.id), "username": user.username, "role": user.role}
    )

    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        user=UserResponse.model_validate(user)
    )

@router.get("/me", response_model=UserResponse)
async def get_my_profile(current_user: User = Depends(get_current_user)):
    """获取当前登录用户的资料与 VIP 实时状态"""
    return current_user

@router.post("/grant-vip", response_model=MessageResponse)
async def grant_vip(req: GrantVipRequest, db: AsyncSession = Depends(get_db)):
    """为指定用户开通或延期 VIP 权益 (运营/测试)"""
    stmt = select(User).where(User.username == req.username)
    res = await db.execute(stmt)
    user = res.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User '{req.username}' not found"
        )

    now = datetime.datetime.now(datetime.timezone.utc)
    # 若已经是有效 VIP，则在现有到期时间上顺延，否则从当前时间起算
    if user.vip_expire_at and user.vip_expire_at.replace(tzinfo=datetime.timezone.utc) > now:
        base_time = user.vip_expire_at.replace(tzinfo=datetime.timezone.utc)
    else:
        base_time = now

    new_expire = base_time + datetime.timedelta(days=req.days)
    user.vip_expire_at = new_expire
    if user.role == "user":
        user.role = "vip"

    await db.commit()
    await db.refresh(user)

    return MessageResponse(
        success=True,
        message=f"Successfully granted {req.days} days VIP to {req.username}",
        data={
            "username": user.username,
            "role": user.role,
            "is_vip": user.is_vip,
            "vip_expire_at": user.vip_expire_at.isoformat()
        }
    )

@router.get("/vip-check", response_model=MessageResponse)
async def vip_only_endpoint(current_vip: User = Depends(require_vip)):
    """测试端点：验证 VIP 权限拦截守卫是否生效"""
    return MessageResponse(
        success=True,
        message=f"Welcome VIP member {current_vip.username}! Access granted.",
        data={"user_id": current_vip.id, "vip_expire_at": str(current_vip.vip_expire_at)}
    )
