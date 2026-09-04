import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.pool import StaticPool
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from common_server.main import app
from common_server.database import Base, get_db
import common_server.models  # noqa: F401

# 创建完全隔离的测试内存数据库，绝不触碰本地开发/生产的 common.db
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

@pytest_asyncio.fixture(autouse=True)
async def prepare_database():
    """每个测试运行前使用内存数据库初始化与清理，严禁影响生产或开发库"""
    app.dependency_overrides[get_db] = override_get_db
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_auth_full_lifecycle():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. 注册首位用户 (自动升级为 admin)
        reg_resp = await client.post("/api/v1/auth/register", json={
            "username": "admin_trader",
            "password": "Password123!",
            "email": "admin@quant.com"
        })
        assert reg_resp.status_code == 201, reg_resp.text
        admin_data = reg_resp.json()
        assert admin_data["username"] == "admin_trader"
        assert admin_data["role"] == "admin"
        assert admin_data["is_vip"] is True  # admin 自动具备 VIP 权限

        # 2. 重复注册检测 (应返回 400)
        dup_resp = await client.post("/api/v1/auth/register", json={
            "username": "admin_trader",
            "password": "Password123!"
        })
        assert dup_resp.status_code == 400

        # 3. 注册第二位普通用户 (role 应为 user)
        reg_user2 = await client.post("/api/v1/auth/register", json={
            "username": "normal_user",
            "password": "NormalPassword123!",
            "email": "user2@quant.com"
        })
        assert reg_user2.status_code == 201
        user2_data = reg_user2.json()
        assert user2_data["username"] == "normal_user"
        assert user2_data["role"] == "user"
        assert user2_data["is_vip"] is False

        # 4. 错误密码登录检测 (应返回 401)
        bad_login = await client.post("/api/v1/auth/login", json={
            "username": "normal_user",
            "password": "WrongPassword!"
        })
        assert bad_login.status_code == 401

        # 5. 正确登录并获取 JWT Token
        login_resp = await client.post("/api/v1/auth/login", json={
            "username": "normal_user",
            "password": "NormalPassword123!"
        })
        assert login_resp.status_code == 200
        token_data = login_resp.json()
        token = token_data["access_token"]
        assert token is not None
        assert token_data["token_type"] == "bearer"

        # 6. 携带 Token 获取当前用户信息 (/me)
        me_resp = await client.get("/api/v1/auth/me", headers={
            "Authorization": f"Bearer {token}"
        })
        assert me_resp.status_code == 200
        assert me_resp.json()["username"] == "normal_user"

        # 7. 未获 VIP 访问 VIP 端点检测 (应被守卫拦截 403)
        vip_check_fail = await client.get("/api/v1/auth/vip-check", headers={
            "Authorization": f"Bearer {token}"
        })
        assert vip_check_fail.status_code == 403

        # 8. 为用户开通 30 天 VIP
        grant_resp = await client.post("/api/v1/auth/grant-vip", json={
            "username": "normal_user",
            "days": 30
        })
        assert grant_resp.status_code == 200
        assert grant_resp.json()["data"]["is_vip"] is True

        # 9. 再次访问 VIP 端点 (应成功放行 200)
        vip_check_success = await client.get("/api/v1/auth/vip-check", headers={
            "Authorization": f"Bearer {token}"
        })
        assert vip_check_success.status_code == 200
        assert "Welcome VIP member normal_user" in vip_check_success.json()["message"]

@pytest.mark.asyncio
async def test_security_and_health_endpoints():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. 健康检查
        health = await client.get("/health")
        assert health.status_code == 200
        assert health.json()["status"] == "healthy"

        # 2. 无 Token 访问受保护路由 (应返回 401)
        no_token = await client.get("/api/v1/auth/me")
        assert no_token.status_code == 401

        # 3. 伪造/篡改的 Token 访问 (应返回 401)
        fake_token = await client.get("/api/v1/auth/me", headers={
            "Authorization": "Bearer fake.jwt.token.here"
        })
        assert fake_token.status_code == 401
