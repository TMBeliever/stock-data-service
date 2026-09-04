from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from common_server.config import settings

# 异步数据库引擎
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {}
)

# 异步会话工厂
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False
)

# 模型声明基类
class Base(DeclarativeBase):
    pass

# FastAPI 依赖注入：获取数据库会话
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()

# 数据库自动初始化 (建表)
async def init_db():
    import common_server.models  # noqa: F401 - 确保所有 ORM 模型类注册到 Base.metadata
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

