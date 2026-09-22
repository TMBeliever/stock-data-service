import os
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from asset_server.config import settings

# 确保 SQLite 数据库本地目录存在
if "sqlite" in settings.DATABASE_URL:
    db_path = settings.DATABASE_URL.split(":///")[-1]
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {},
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db():
    import asset_server.models  # noqa: F401
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # 兼容 SQLite 轻量热迁移补齐存款计息与周期字段
        def _check_and_add_columns(sync_conn):
            from sqlalchemy import text
            cursor = sync_conn.connection.cursor()
            cursor.execute("PRAGMA table_info(asset_items)")
            columns = [row[1] for row in cursor.fetchall()]
            new_cols = {
                "deposit_type": "VARCHAR(16) DEFAULT 'NONE'",
                "interest_rate": "FLOAT DEFAULT 0.0",
                "start_date": "VARCHAR(32)",
                "end_date": "VARCHAR(32)",
                "settlement_cycle": "VARCHAR(32) DEFAULT 'MATURITY'",
                "auto_rollover": "BOOLEAN DEFAULT 0",
            }
            for col, col_type in new_cols.items():
                if col not in columns:
                    cursor.execute(f"ALTER TABLE asset_items ADD COLUMN {col} {col_type}")
            cursor.close()

        await conn.run_sync(_check_and_add_columns)
