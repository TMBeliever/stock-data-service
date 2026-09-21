import logging
from typing import Dict, Tuple, Optional
import httpx
from fastapi import Request, Response
from fastapi.responses import StreamingResponse, JSONResponse
from api_gateway.config import settings

logger = logging.getLogger("api_gateway.proxy")

# 全局复用的异步 HTTP 连接池
_http_client: Optional[httpx.AsyncClient] = None


def get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=600.0, write=60.0, pool=30.0),
            limits=httpx.Limits(max_keepalive_connections=100, max_connections=300),
            follow_redirects=True,
            trust_env=False,  # 内部微服务通信绝不走外部网络代理
        )
    return _http_client


async def close_http_client():
    global _http_client
    if _http_client and not _http_client.is_closed:
        await _http_client.aclose()
        _http_client = None


def resolve_upstream_target(path: str) -> Tuple[str, str]:
    """
    根据请求路径将请求动态路由到目标微服务。
    返回: (target_base_url, target_path)
    """
    # 1. 用户中心与鉴权服务
    if path.startswith("/api/v1/auth") or path.startswith("/api/v1/user"):
        return settings.COMMON_SERVER_URL, path

    # 2. 资产服务 (未来资产中枢)
    if path.startswith("/api/v1/asset"):
        return settings.ASSET_SERVER_URL, path

    # 3. 投研与自愈智能体
    if path.startswith("/api/v1/agent"):
        return settings.QUANT_AGENT_URL, path

    # 4. 微信助理服务
    if path.startswith("/api/v1/weixin"):
        return settings.WEIXIN_BOT_URL, path

    # 5. AI 模型推理与兼容接口
    if (
        path.startswith("/api/v1/ai")
        or path.startswith("/v1")
        or path.startswith("/chat/completions")
        or path.startswith("/models")
        or path.startswith("/messages")
    ):
        return settings.AI_CORE_URL, path

    # 6. 行情数据底座 (/stock/xxx -> 映射至 stock-data 对应端点)
    if path.startswith("/stock"):
        sub_path = path[len("/stock"):]
        if not sub_path.startswith("/"):
            sub_path = "/" + sub_path
        return settings.STOCK_DATA_URL, sub_path

    # 7. MCP 网关服务
    if path.startswith("/mcp"):
        return settings.MCP_GATEWAY_URL, path

    # 8. 默认量化业务与回测中枢 (兜底所有 /api/v1/* 策略与回测等)
    if path.startswith("/api/v1"):
        return settings.QUANT_SERVER_URL, path

    # 其他未匹配前缀默认回退给量化服务
    return settings.QUANT_SERVER_URL, path


HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
}


async def forward_request(
    request: Request,
    forward_headers: Dict[str, str],
    target_base_url: str,
    target_path: str,
) -> Response:
    """
    向目标微服务发起异步反向代理转发，支持全双工数据流与 SSE 打字机流式免缓冲透传
    """
    client = get_http_client()
    url = f"{target_base_url.rstrip('/')}{target_path}"

    # 附加原始查询参数
    if request.url.query:
        url = f"{url}?{request.url.query}"

    # 流式读取客户端传入的请求体
    req_body = request.stream()

    try:
        upstream_req = client.build_request(
            method=request.method,
            url=url,
            headers=forward_headers,
            content=req_body,
        )

        upstream_resp = await client.send(upstream_req, stream=True)

        # 过滤 Hop-by-hop 响应头
        resp_headers = {}
        for k, v in upstream_resp.headers.items():
            if k.lower() not in HOP_BY_HOP_HEADERS:
                resp_headers[k] = v

        content_type = upstream_resp.headers.get("content-type", "").lower()
        is_streaming = (
            "text/event-stream" in content_type
            or "application/x-ndjson" in content_type
            or upstream_resp.headers.get("transfer-encoding") == "chunked"
        )

        if is_streaming:
            # 流式免缓冲直出 (如 AI 思考流、终端进度输出)
            resp_headers["cache-control"] = "no-cache"
            resp_headers["x-accel-buffering"] = "no"

            async def stream_generator():
                try:
                    async for chunk in upstream_resp.aiter_bytes():
                        yield chunk
                finally:
                    await upstream_resp.aclose()

            return StreamingResponse(
                stream_generator(),
                status_code=upstream_resp.status_code,
                headers=resp_headers,
                media_type=content_type,
            )
        else:
            # 非流式普通响应直接读取全量内容并关闭
            content = await upstream_resp.aread()
            await upstream_resp.aclose()
            return Response(
                content=content,
                status_code=upstream_resp.status_code,
                headers=resp_headers,
                media_type=content_type or None,
            )

    except httpx.ConnectError:
        logger.error(f"[Gateway 502] 目标服务离线或无法连接: {url}")
        return JSONResponse(
            status_code=502,
            content={
                "code": "UPSTREAM_OFFLINE",
                "message": f"下游微服务暂不可用 ({target_base_url})，请检查服务是否已启动",
                "target_url": url,
            },
        )
    except httpx.TimeoutException:
        logger.error(f"[Gateway 504] 目标服务响应超时: {url}")
        return JSONResponse(
            status_code=504,
            content={
                "code": "GATEWAY_TIMEOUT",
                "message": f"微服务响应超时 ({target_base_url})",
                "target_url": url,
            },
        )
    except Exception as e:
        logger.exception(f"[Gateway 500] 代理转发异常: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={
                "code": "GATEWAY_INTERNAL_ERROR",
                "message": f"网关内部转发异常: {str(e)}",
            },
        )
