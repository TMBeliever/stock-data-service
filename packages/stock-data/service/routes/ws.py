import json
import asyncio
import datetime
from typing import Dict, Set, List
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from core.models import parse_symbol, format_symbol, KlinePeriod, AdjustType
from sdk import StockDataSDK

router = APIRouter(tags=["WebSocket"])
sdk = StockDataSDK()

class ConnectionManager:
    """
    WebSocket 连接与主题订阅管理器:
    - 管理客户端全双工长连接
    - 支持客户端订阅单只或多只标的
    - 提供心跳保活 (Ping/Pong)
    """
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.subscriptions: Dict[WebSocket, Set[str]] = {}

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        self.subscriptions[websocket] = set()

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        if websocket in self.subscriptions:
            del self.subscriptions[websocket]

    def subscribe(self, websocket: WebSocket, symbol: str, max_subscriptions: int = 50) -> bool:
        if websocket in self.subscriptions:
            if len(self.subscriptions[websocket]) >= max_subscriptions:
                return False
            self.subscriptions[websocket].add(symbol)
            return True
        return False

    def unsubscribe(self, websocket: WebSocket, symbol: str):
        if websocket in self.subscriptions and symbol in self.subscriptions[websocket]:
            self.subscriptions[websocket].remove(symbol)

    async def send_json(self, websocket: WebSocket, data: dict):
        try:
            await websocket.send_json(data)
        except Exception:
            pass

manager = ConnectionManager()

@router.websocket("/ws/market")
async def websocket_market_endpoint(websocket: WebSocket):
    """
    WebSocket 行情查询与快照订阅网关 (WebSocket Market Gateway):
    - 协议指令:
      1. 订阅行情: {"action": "subscribe", "symbol": "002594", "period": "1d"} (单连接上限50只)
      2. 取消订阅: {"action": "unsubscribe", "symbol": "002594"}
      3. 即时查询: {"action": "query", "symbol": "002594", "period": "1d", "limit": 10} (limit上限1000)
      4. 心跳保活: {"action": "ping"} -> 服务端回复 pong
    """
    await manager.connect(websocket)
    try:
        # 发送欢迎与连接成功事件
        await manager.send_json(websocket, {
            "type": "connected",
            "message": "Connected to Global Stock Data WebSocket Gateway",
            "server_time": datetime.datetime.now(datetime.timezone.utc).isoformat()
        })

        while True:
            text = await websocket.receive_text()
            try:
                msg = json.loads(text)
            except Exception:
                await manager.send_json(websocket, {"type": "error", "message": "Invalid JSON format"})
                continue

            action = msg.get("action")

            # 1. 心跳响应
            if action == "ping":
                await manager.send_json(websocket, {
                    "type": "pong",
                    "timestamp": int(datetime.datetime.now(datetime.timezone.utc).timestamp() * 1000)
                })

            # 2. 行情订阅与即时首包下发
            elif action == "subscribe":
                raw_sym = msg.get("symbol")
                if not raw_sym:
                    await manager.send_json(websocket, {"type": "error", "message": "Missing 'symbol' parameter"})
                    continue

                ticker, m, t = parse_symbol(raw_sym)
                clean_sym = format_symbol(ticker, m, t)
                ok = manager.subscribe(websocket, clean_sym, max_subscriptions=50)
                if not ok:
                    await manager.send_json(websocket, {
                        "type": "error",
                        "message": "Maximum subscription limit reached (50 symbols per connection)"
                    })
                    continue

                # 拉取该标的最新 1 根日K作为初始快照推送
                period = msg.get("period", "1d")
                df = await sdk.get_kline_async(symbol=clean_sym, period=period, adjust="qfq")
                latest_tick = None
                if df is not None and not df.is_empty():
                    last_row = df.tail(1).to_dicts()[0]
                    latest_tick = {
                        "timestamp": last_row["timestamp"],
                        "open": round(last_row["open"], 4),
                        "high": round(last_row["high"], 4),
                        "low": round(last_row["low"], 4),
                        "close": round(last_row["close"], 4),
                        "volume": last_row["volume"]
                    }

                await manager.send_json(websocket, {
                    "type": "subscribed",
                    "symbol": clean_sym,
                    "period": period,
                    "latest": latest_tick
                })

            # 3. 取消订阅
            elif action == "unsubscribe":
                raw_sym = msg.get("symbol")
                if raw_sym:
                    ticker, m, t = parse_symbol(raw_sym)
                    clean_sym = format_symbol(ticker, m, t)
                    manager.unsubscribe(websocket, clean_sym)
                    await manager.send_json(websocket, {
                        "type": "unsubscribed",
                        "symbol": clean_sym
                    })

            # 4. 即时行情查询 (Zero-Copy 极速返回)
            elif action == "query":
                raw_sym = msg.get("symbol")
                period = msg.get("period", "1d")
                raw_limit = int(msg.get("limit", 10))
                limit = max(1, min(raw_limit, 1000)) # 限制最大 1000 根

                if not raw_sym:
                    await manager.send_json(websocket, {"type": "error", "message": "Missing 'symbol' parameter"})
                    continue

                ticker, m, t = parse_symbol(raw_sym)
                clean_sym = format_symbol(ticker, m, t)
                df = await sdk.get_kline_async(symbol=clean_sym, period=period, adjust="qfq")
                if df is not None and not df.is_empty():
                    records = df.tail(limit).to_dicts()
                    await manager.send_json(websocket, {
                        "type": "query_result",
                        "symbol": clean_sym,
                        "period": period,
                        "count": len(records),
                        "data": records
                    })
                else:
                    await manager.send_json(websocket, {
                        "type": "error",
                        "symbol": clean_sym,
                        "message": "No data found"
                    })

            else:
                await manager.send_json(websocket, {"type": "error", "message": f"Unknown action: {action}"})

    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        manager.disconnect(websocket)
