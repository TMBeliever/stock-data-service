import uuid
from typing import Optional, Dict, Any, Tuple
import jwt
from fastapi import Request
from api_gateway.config import settings, AuthPolicy


# 客户端禁止随意伪造的内部信任请求头
UNTRUSTED_INTERNAL_HEADERS = {
    "x-user-id",
    "x-user-name",
    "x-user-role",
    "x-user-vip",
    "x-gateway-verified",
}

# =========================================================================
# 权限漏斗设计：第二层 —— 接口级精确重载覆盖表 (Endpoint-Level Overrides)
# 优先级高于所属服务级默认策略
# =========================================================================
ENDPOINT_POLICY_OVERRIDES: Dict[str, AuthPolicy] = {
    # 接口级放行 (白名单接口)
    "/health": AuthPolicy.ANONYMOUS,
    "/docs": AuthPolicy.ANONYMOUS,
    "/openapi.json": AuthPolicy.ANONYMOUS,
    "/redoc": AuthPolicy.ANONYMOUS,
    "/api/v1/auth/login": AuthPolicy.ANONYMOUS,
    "/api/v1/auth/register": AuthPolicy.ANONYMOUS,

    # 接口级收紧 (auth 服务全局默认为 ANONYMOUS，但 /me 端点精确收窄为 USER_JWT)
    "/api/v1/auth/me": AuthPolicy.USER_JWT,
    "/api/v1/auth/grant-vip": AuthPolicy.ADMIN_ONLY,
}


def decode_jwt(token: str) -> Optional[Dict[str, Any]]:
    """校验并解码 JWT Token，过期或签名不合规时返回 None"""
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM]
        )
        return payload
    except (jwt.PyJWTError, Exception):
        return None


def extract_token_from_header(auth_header: Optional[str]) -> Optional[str]:
    """从 Authorization 标头中提取 Bearer 字符串"""
    if not auth_header:
        return None
    parts = auth_header.strip().split(" ")
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1]
    return None


def match_funnel_policy(path: str) -> AuthPolicy:
    """
    权限漏斗判定引擎：从接口级精确匹配 -> 服务级前缀收敛 -> 全局默认兜底
    """
    normalized = path.rstrip("/")
    if not normalized:
        normalized = "/"

    # 1. 漏斗最深层：接口级精确匹配 (Highest Priority)
    if normalized in ENDPOINT_POLICY_OVERRIDES:
        return ENDPOINT_POLICY_OVERRIDES[normalized]

    # 2. 漏斗中间层：服务级领域匹配 (Service-Level Defaults)
    # AI 算力服务域
    if (
        normalized.startswith("/v1")
        or normalized == "/messages"
        or normalized.startswith("/messages/")
        or normalized == "/chat/completions"
        or normalized == "/models"
        or normalized.startswith("/api/v1/ai")
    ):
        return settings.SERVICE_AUTH_AI

    # 用户核心资产与账簿服务域
    if normalized.startswith("/api/v1/user"):
        return settings.SERVICE_AUTH_USER
    if normalized.startswith("/api/v1/asset"):
        return settings.SERVICE_AUTH_ASSET

    # 投研专家与自愈 Agent 域
    if normalized.startswith("/api/v1/agent"):
        return settings.SERVICE_AUTH_AGENT

    # 行情底座域
    if normalized.startswith("/stock") or normalized.startswith("/ws"):
        return settings.SERVICE_AUTH_STOCK

    # 用户认证域 (除 /me 外的默认 auth 路径)
    if normalized.startswith("/api/v1/auth"):
        return settings.SERVICE_AUTH_COMMON_AUTH

    # MCP 协议网关
    if normalized.startswith("/mcp"):
        return settings.SERVICE_AUTH_MCP

    # 量化策略与回测中枢 (兜底常规 /api/v1/*)
    if normalized.startswith("/api/v1"):
        return settings.SERVICE_AUTH_QUANT

    # 3. 漏斗顶层：全局未知端点默认兜底 (最小权限原则)
    return AuthPolicy.OPTIONAL_JWT


def resolve_auth_context(request: Request) -> Tuple[bool, int, Optional[str], Dict[str, str]]:
    """
    基于漏斗权限策略执行身份鉴权与请求头清洗注入：
    返回: (is_allowed, error_status_code, error_message, forward_headers)
    """
    path = request.url.path
    auth_policy = match_funnel_policy(path)

    auth_header = request.headers.get("authorization")
    token = extract_token_from_header(auth_header)

    forward_headers: Dict[str, str] = {}

    # 1. 统一注入全链路 Trace ID
    req_id = request.headers.get("x-request-id") or f"req-{uuid.uuid4().hex[:12]}"
    forward_headers["x-request-id"] = req_id

    # 2. 安全防伪造清洗：剔除客户端私自夹带的不可信内部头
    for k, v in request.headers.items():
        k_lower = k.lower()
        if k_lower in UNTRUSTED_INTERNAL_HEADERS:
            continue
        if k_lower in ("host", "content-length"):
            continue
        forward_headers[k_lower] = v

    # 3. 针对不同策略执行漏斗校验
    # 策略 A: 完全匿名公开 (ANONYMOUS)
    if auth_policy == AuthPolicy.ANONYMOUS:
        # 特殊处理：如果是去往 AI 服务的请求
        is_ai_path = (
            path.startswith("/v1")
            or path.startswith("/messages")
            or path.startswith("/chat/completions")
            or path.startswith("/models")
            or path.startswith("/api/v1/ai")
        )
        if is_ai_path:
            # 若客户端未携带任何 Key，网关自动附加上受信的内部 Key，保护底层 ai-core
            if not auth_header and not request.headers.get("x-api-key"):
                forward_headers["authorization"] = f"Bearer {settings.INTERNAL_AI_CORE_KEY}"
        return True, 200, None, forward_headers

    # 策略 B: 严格前台用户鉴权 (USER_JWT)
    user_payload: Optional[Dict[str, Any]] = None
    if token:
        user_payload = decode_jwt(token)

    if auth_policy in (AuthPolicy.USER_JWT, AuthPolicy.ADMIN_ONLY):
        if not user_payload:
            return False, 401, "当前端点需要用户登录有效凭证，请登录后重试", forward_headers

        user_id = str(user_payload.get("sub", ""))
        username = str(user_payload.get("username", ""))
        role = str(user_payload.get("role", "user"))

        if auth_policy == AuthPolicy.ADMIN_ONLY and role != "admin":
            return False, 403, "当前操作仅限平台管理员执行", forward_headers

        is_vip_or_admin = (role in ("vip", "admin"))
        forward_headers["x-user-id"] = user_id
        forward_headers["x-user-name"] = username
        forward_headers["x-user-role"] = role
        forward_headers["x-user-vip"] = "true" if is_vip_or_admin else "false"
        forward_headers["x-gateway-verified"] = "true"
        return True, 200, None, forward_headers

    # 策略 C: 可选鉴权 (OPTIONAL_JWT)
    if auth_policy == AuthPolicy.OPTIONAL_JWT:
        if token:
            user_payload = decode_jwt(token)
            if not user_payload:
                return False, 401, "提供的身份凭据无效或已过期", forward_headers

            user_id = str(user_payload.get("sub", ""))
            username = str(user_payload.get("username", ""))
            role = str(user_payload.get("role", "user"))
            forward_headers["x-user-id"] = user_id
            forward_headers["x-user-name"] = username
            forward_headers["x-user-role"] = role
            forward_headers["x-user-vip"] = "true" if role in ("vip", "admin") else "false"
            forward_headers["x-gateway-verified"] = "true"
        else:
            forward_headers["x-user-role"] = "guest"

        return True, 200, None, forward_headers

    return True, 200, None, forward_headers
