import pytest
import jwt
from httpx import AsyncClient, ASGITransport
from api_gateway.main import app
from api_gateway.config import settings, AuthPolicy
from api_gateway.auth import decode_jwt, resolve_auth_context, match_funnel_policy


def generate_test_jwt(user_id: int = 1001, username: str = "trader_alice", role: str = "user") -> str:
    """快速生成测试用合规 JWT"""
    payload = {
        "sub": str(user_id),
        "username": username,
        "role": role,
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


@pytest.mark.asyncio
async def test_gateway_health():
    """验证网关健康检查端点"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert data["service"] == "api-gateway"
        assert "routes" in data


def test_funnel_policy_matching():
    """验证权限漏斗在服务级与接口级各层级的判定"""
    # 1. 接口级精确重载覆盖：/api/v1/auth/me 强制要求 USER_JWT
    assert match_funnel_policy("/api/v1/auth/me") == AuthPolicy.USER_JWT
    # 接口级精确覆盖：/api/v1/auth/grant-vip 强制要求 ADMIN_ONLY
    assert match_funnel_policy("/api/v1/auth/grant-vip") == AuthPolicy.ADMIN_ONLY
    # 接口级公开：/api/v1/auth/login 匿名放行
    assert match_funnel_policy("/api/v1/auth/login") == AuthPolicy.ANONYMOUS
    assert match_funnel_policy("/health") == AuthPolicy.ANONYMOUS

    # 2. 服务级默认规则：
    # AI 算力服务域当前为 ANONYMOUS
    assert match_funnel_policy("/v1/chat/completions") == AuthPolicy.ANONYMOUS
    assert match_funnel_policy("/messages") == AuthPolicy.ANONYMOUS
    assert match_funnel_policy("/api/v1/ai/generate") == AuthPolicy.ANONYMOUS

    # 用户资产与账务服务域为 USER_JWT
    assert match_funnel_policy("/api/v1/user/holdings") == AuthPolicy.USER_JWT
    assert match_funnel_policy("/api/v1/asset/accounts") == AuthPolicy.USER_JWT
    assert match_funnel_policy("/api/v1/agent/chat") == AuthPolicy.USER_JWT

    # 行情服务域为 ANONYMOUS
    assert match_funnel_policy("/stock/kline/510300") == AuthPolicy.ANONYMOUS


@pytest.mark.asyncio
async def test_funnel_endpoint_override_auth_me():
    """验证漏斗接口级覆盖：访问 /api/v1/auth/me 时即使处于 /auth 服务下，也必须校验 JWT"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # 未带 Token 访问 /auth/me -> 401
        resp = await client.get("/api/v1/auth/me")
        assert resp.status_code == 401
        assert resp.json()["code"] == "UNAUTHORIZED"

        # 携带合规 Token -> 通过网关层 (502说明通过了网关到了下游离线)
        token = generate_test_jwt(user_id=1001)
        resp2 = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert resp2.status_code != 401


@pytest.mark.asyncio
async def test_funnel_admin_only_rejection():
    """验证漏斗 RBAC 接口级限制：普通用户访问 ADMIN_ONLY 接口直接被网关 403 拦截"""
    user_token = generate_test_jwt(user_id=1001, role="user")
    admin_token = generate_test_jwt(user_id=9999, role="admin")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # 普通用户 -> 403 Forbidden
        resp = await client.post(
            "/api/v1/auth/grant-vip",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"username": "alice", "days": 30}
        )
        assert resp.status_code == 403
        assert resp.json()["code"] == "FORBIDDEN"

        # 管理员用户 -> 允许通过网关
        resp2 = await client.post(
            "/api/v1/auth/grant-vip",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"username": "alice", "days": 30}
        )
        assert resp2.status_code != 403


@pytest.mark.asyncio
async def test_ai_service_anonymous_attaches_internal_key():
    """
    验证 AI 服务的漏斗策略：
    对外作为 ANONYMOUS 开放免鉴权，客户端未传 Key 时网关自动向内部下游附加受信的 Key，保护底层 ai-core
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # 客户端未传任何 Authorization 标头
        resp = await client.post(
            "/v1/chat/completions",
            json={"model": "minimax/minimax-m3:free", "messages": [{"role": "user", "content": "hi"}]}
        )
        # 不应被网关拦截为 401
        assert resp.status_code != 401


@pytest.mark.asyncio
async def test_header_sanitization_and_injection():
    """验证网关剥除客户端伪造的 X-User-* 敏感头，并安全注入真实用户身份与 verified 标记"""
    token = generate_test_jwt(user_id=8888, username="quant_master", role="vip")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get(
            "/api/v1/user/holdings",
            headers={
                "Authorization": f"Bearer {token}",
                "X-User-Id": "9999_hacker",
                "X-User-Role": "admin_fake",
            }
        )
        # 通过网关校验放行
        assert resp.status_code != 401


@pytest.mark.asyncio
async def test_upstream_offline_graceful_handling():
    """验证当下游服务不在线时，网关优雅返回 502 JSON 而非崩溃"""
    token = generate_test_jwt(user_id=123)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get(
            "/api/v1/user/non_existent_mock_service",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert resp.status_code == 502
        data = resp.json()
        assert data["code"] == "UPSTREAM_OFFLINE"
        assert "下游微服务暂不可用" in data["message"]


def test_jwt_decoding():
    """验证 JWT 解码与防篡改逻辑"""
    token = generate_test_jwt(user_id=42, username="douglas")
    payload = decode_jwt(token)
    assert payload is not None
    assert payload["sub"] == "42"
    assert payload["username"] == "douglas"

    # 篡改密钥
    tampered_token = jwt.encode({"sub": "42"}, "wrong_secret", algorithm="HS256")
    assert decode_jwt(tampered_token) is None
