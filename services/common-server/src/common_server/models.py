import datetime
from typing import Optional
from sqlalchemy import String, Boolean, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column
from common_server.database import Base

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    email: Mapped[Optional[str]] = mapped_column(String(128), unique=True, index=True, nullable=True)
    hashed_password: Mapped[str] = mapped_column(String(256), nullable=False)
    role: Mapped[str] = mapped_column(String(32), default="user", nullable=False)  # user, vip, admin
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    vip_expire_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False
    )

    @property
    def is_vip(self) -> bool:
        """动态判断用户当前是否具备有效 VIP 权益"""
        if not self.is_active:
            return False
        if self.role == "admin":
            return True
        if self.role == "vip":
            if self.vip_expire_at is None:
                return True
            now = datetime.datetime.now(datetime.timezone.utc)
            # 处理时区一致性比较
            exp = self.vip_expire_at
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=datetime.timezone.utc)
            return exp > now
        return False
