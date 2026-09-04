import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.pool import StaticPool
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from common_server.main import app
from common_server.database import Base, get_db
import common_server.models  # noqa: F401

test_engine = create_async_engine(
    "sqlite+aiosqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = async_sessionmaker(
    bind=test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False
)

async def override_get_db():
    async with TestingSessionLocal() as session:
        yield session

app.dependency_overrides[get_db] = override_get_db

@pytest_asyncio.fixture(autouse=True)
async def prepare_database():
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.mark.asyncio
async def test_user_strategies_and_backtest_records():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. 注册首位管理员并登录
        reg_admin = await client.post("/api/v1/auth/register", json={
            "username": "super_vip",
            "password": "Password123!"
        })
        assert reg_admin.status_code == 201
        
        login_resp = await client.post("/api/v1/auth/login", json={
            "username": "super_vip",
            "password": "Password123!"
        })
        assert login_resp.status_code == 200
        token = login_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # 2. 保存新策略
        strat_code = "class MyStrategy(BaseStrategy): pass"
        create_resp = await client.post("/api/v1/user/strategies", headers=headers, json={
            "name": "沪深300双均线策略",
            "description": "测试描述",
            "code": strat_code,
            "symbol": "510300.SH.ETF"
        })
        assert create_resp.status_code == 201, create_resp.text
        strat_data = create_resp.json()
        assert strat_data["name"] == "沪深300双均线策略"
        strat_id = strat_data["id"]

        # 3. 获取策略列表
        list_resp = await client.get("/api/v1/user/strategies", headers=headers)
        assert list_resp.status_code == 200
        strategies = list_resp.json()
        assert len(strategies) == 1
        assert strategies[0]["id"] == strat_id

        # 4. 更新策略
        update_resp = await client.put(f"/api/v1/user/strategies/{strat_id}", headers=headers, json={
            "name": "重命名策略",
            "code": "new code"
        })
        assert update_resp.status_code == 200
        assert update_resp.json()["name"] == "重命名策略"
        assert update_resp.json()["code"] == "new code"

        # 5. 保存回测记录
        bt_resp = await client.post("/api/v1/user/backtests", headers=headers, json={
            "strategy_id": strat_id,
            "strategy_name": "重命名策略",
            "symbol": "510300.SH.ETF",
            "start_date": "2023-01-01",
            "end_date": "2024-01-01",
            "initial_cash": 100000.0,
            "final_equity": 125000.0,
            "total_return": 0.25,
            "annualized_return": 0.25,
            "max_drawdown": 0.08,
            "sharpe_ratio": 1.85,
            "win_rate": 0.65,
            "total_trades": 24
        })
        assert bt_resp.status_code == 201, bt_resp.text
        bt_data = bt_resp.json()
        assert bt_data["total_return"] == 0.25
        bt_id = bt_data["id"]

        # 6. 获取回测记录列表
        bt_list_resp = await client.get("/api/v1/user/backtests", headers=headers)
        assert bt_list_resp.status_code == 200
        assert len(bt_list_resp.json()) == 1

        # 7. 删除回测记录
        del_bt_resp = await client.delete(f"/api/v1/user/backtests/{bt_id}", headers=headers)
        assert del_bt_resp.status_code == 200

        # 8. 删除策略
        del_strat_resp = await client.delete(f"/api/v1/user/strategies/{strat_id}", headers=headers)
        assert del_strat_resp.status_code == 200
