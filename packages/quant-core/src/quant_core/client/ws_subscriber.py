import asyncio
import json
from typing import List, Callable, Optional
import websockets
from quant_core.config import quant_config
from quant_core.core.models import Snapshot
from quant_core.core.events import Event, EventType, event_bus

class WSSubscriber:
    """
    WebSocket 实时市场行情订阅客户端：
    长连接对接 stock-data 的 /ws/market 网关，
    收到快照推送时实时分发到事件总线与策略回调。
    """
    def __init__(self, ws_url: Optional[str] = None):
        self.ws_url = ws_url or quant_config.DATA_SERVICE_WS
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._subscribed_symbols: List[str] = []

    async def connect_and_listen(self, symbols: List[str], on_snapshot: Optional[Callable[[Snapshot], None]] = None):
        self._running = True
        self._subscribed_symbols = list(symbols)
        
        while self._running:
            try:
                async with websockets.connect(self.ws_url) as ws:
                    # 订阅指令
                    sub_payload = {"action": "subscribe", "symbols": self._subscribed_symbols}
                    await ws.send(json.dumps(sub_payload))
                    
                    while self._running:
                        msg = await ws.recv()
                        data = json.loads(msg)
                        
                        if data.get("type") in ("snapshot", "update"):
                            payload = data.get("data", {})
                            if isinstance(payload, list):
                                for item in payload:
                                    self._handle_snapshot_item(item, on_snapshot)
                            elif isinstance(payload, dict):
                                self._handle_snapshot_item(payload, on_snapshot)
            except Exception:
                if self._running:
                    # 5 秒重连
                    await asyncio.sleep(5)

    def _handle_snapshot_item(self, item: dict, callback: Optional[Callable[[Snapshot], None]]):
        try:
            snapshot = Snapshot(**item)
            event_bus.publish(Event(EventType.SNAPSHOT, snapshot, snapshot.timestamp))
            if callback:
                callback(snapshot)
        except Exception:
            pass

    def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
