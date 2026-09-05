import datetime
from typing import Optional
from sqlalchemy import String, Boolean, DateTime, ForeignKey, func
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


class UserStrategy(Base):
    """用户自定义量化策略库"""
    __tablename__ = "user_strategies"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    code: Mapped[str] = mapped_column(String, nullable=False)  # Python 源码
    symbol: Mapped[str] = mapped_column(String(32), default="510300.SH.ETF", nullable=False)
    
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


class BacktestRecord(Base):
    """用户历史回测归档记录"""
    __tablename__ = "backtest_records"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    strategy_id: Mapped[Optional[int]] = mapped_column(ForeignKey("user_strategies.id", ondelete="SET NULL"), nullable=True)
    strategy_name: Mapped[str] = mapped_column(String(128), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    start_date: Mapped[str] = mapped_column(String(32), nullable=False)
    end_date: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    
    initial_cash: Mapped[float] = mapped_column(nullable=False)
    final_equity: Mapped[float] = mapped_column(nullable=False)
    total_return: Mapped[float] = mapped_column(nullable=False)
    annualized_return: Mapped[float] = mapped_column(nullable=False)
    max_drawdown: Mapped[float] = mapped_column(nullable=False)
    sharpe_ratio: Mapped[float] = mapped_column(nullable=False)
    win_rate: Mapped[float] = mapped_column(nullable=False)
    total_trades: Mapped[int] = mapped_column(nullable=False)

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )


class UserWatchlist(Base):
    """用户自选股票池/投资组合"""
    __tablename__ = "user_watchlists"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    symbols: Mapped[str] = mapped_column(String, nullable=False)  # JSON 字符串格式: ["510300.SH.ETF", "511010.SH.BOND"]

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


class UserHolding(Base):
    """用户当前资产持仓 (真实或模拟)"""
    __tablename__ = "user_holdings"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    quantity: Mapped[float] = mapped_column(nullable=False, default=100.0)
    avg_cost: Mapped[float] = mapped_column(nullable=False, default=0.0)

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


