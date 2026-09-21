import asyncio
import logging
from fastapi import WebSocket, WebSocketDisconnect
import websockets
from api_gateway.config import settings

logger = logging.getLogger("api_gateway.ws_proxy")


async def forward_websocket(client_ws: WebSocket, path: str):
    """
    全双工 WebSocket 长连接中继通道 (如实时分时/盘口 K 线推送)
    """
    await client_ws.accept()

    # 确定下游 WebSocket 目标地址
    upstream_base_ws = settings.STOCK_DATA_WS_URL.rstrip("/")
    if upstream_base_ws.startswith("http://"):
        upstream_base_ws = "ws://" + upstream_base_ws[7:]
    elif upstream_base_ws.startswith("https://"):
        upstream_base_ws = "wss://" + upstream_base_ws[8:]

    query = client_ws.scope.get("query_string", b"").decode("utf-8")
    target_url = f"{upstream_base_ws}{path}"
    if query:
        target_url = f"{target_url}?{query}"

    try:
        async with websockets.connect(target_url) as upstream_ws:
            # 客户端 -> 下游微服务
            async def client_to_upstream():
                try:
                    while True:
                        msg = await client_ws.receive_text()
                        await upstream_ws.send(msg)
                except (WebSocketDisconnect, asyncio.CancelledError):
                    pass
                except Exception as e:
                    logger.debug(f"WS client_to_upstream error: {e}")

            # 下游微服务 -> 客户端
            async def upstream_to_client():
                try:
                    while True:
                        msg = await upstream_ws.recv()
                        if isinstance(msg, bytes):
                            await client_ws.send_bytes(msg)
                        else:
                            await client_ws.send_text(msg)
                except (WebSocketDisconnect, asyncio.CancelledError):
                    pass
                except Exception as e:
                    logger.debug(f"WS upstream_to_client error: {e}")

            done, pending = await asyncio.wait(
                [
                    asyncio.create_task(client_to_upstream()),
                    asyncio.create_task(upstream_to_client()),
                ],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()

    except Exception as e:
        logger.warning(f"无法建立下游 WebSocket 链接 ({target_url}): {e}")
        try:
            await client_ws.close(code=1011, reason=f"Upstream WS unavailable: {e}")
        except Exception:
            pass
