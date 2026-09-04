import pytest
from fastapi.testclient import TestClient
from service.app import app

@pytest.fixture
def client():
    return TestClient(app)

def test_websocket_market_flow(client):
    """测试 WebSocket 市场实时长连接流程 (连接、Ping/Pong、订阅、即时查询、退订)"""
    with client.websocket_connect("/ws/market") as websocket:
        # 1. 验证握手成功推送
        conn_msg = websocket.receive_json()
        assert conn_msg["type"] == "connected"
        assert "server_time" in conn_msg

        # 2. 验证心跳保活
        websocket.send_json({"action": "ping"})
        pong_msg = websocket.receive_json()
        assert pong_msg["type"] == "pong"
        assert "timestamp" in pong_msg

        # 3. 验证行情订阅与首包推送 (比亚迪 002594)
        websocket.send_json({"action": "subscribe", "symbol": "002594", "period": "1d"})
        sub_msg = websocket.receive_json()
        assert sub_msg["type"] == "subscribed"
        assert sub_msg["symbol"] == "002594.SZ.STK"
        assert sub_msg["period"] == "1d"
        assert sub_msg["latest"] is not None
        assert "close" in sub_msg["latest"]

        # 4. 验证即时查询 (Zero-Copy 极速返回)
        websocket.send_json({"action": "query", "symbol": "002594", "period": "1d", "limit": 5})
        query_msg = websocket.receive_json()
        assert query_msg["type"] == "query_result"
        assert query_msg["symbol"] == "002594.SZ.STK"
        assert query_msg["count"] == 5
        assert len(query_msg["data"]) == 5

        # 5. 验证退订
        websocket.send_json({"action": "unsubscribe", "symbol": "002594"})
        unsub_msg = websocket.receive_json()
        assert unsub_msg["type"] == "unsubscribed"
        assert unsub_msg["symbol"] == "002594.SZ.STK"
