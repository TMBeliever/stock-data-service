import pytest
from fastapi.testclient import TestClient
from service.app import app

pytestmark = pytest.mark.live

@pytest.fixture
def client():
    return TestClient(app)

def test_valuation_ashare_real(client):
    """测试真实 A 股个股估值指标 (比亚迪 002594)"""
    resp = client.get("/api/v1/stock/valuation?symbol=002594")
    assert resp.status_code == 200
    data = resp.json()
    assert data["symbol"] == "002594.SZ.STK"
    assert data["ticker"] == "002594"
    assert data["currency"] == "CNY"
    # 比亚迪真实市盈率约在 20~40 之间
    assert data["pe_ttm"] is not None
    assert 10.0 < data["pe_ttm"] < 100.0
    # 比亚迪真实市净率在 2~6 之间
    assert data["pb"] is not None
    assert 1.0 < data["pb"] < 10.0
    # 总市值高于 5000 亿
    assert data["market_cap_billion"] is not None
    assert data["market_cap_billion"] > 5000.0

def test_valuation_us_real(client):
    """测试真实美股个股估值指标 (苹果 AAPL)"""
    resp = client.get("/api/v1/stock/valuation?symbol=AAPL")
    assert resp.status_code == 200
    data = resp.json()
    assert data["symbol"] == "AAPL.US.STK"
    assert data["ticker"] == "AAPL"
    assert data["currency"] == "USD"
    # 苹果市盈率 PE
    assert data["pe_ttm"] is not None
    assert data["pe_ttm"] > 20.0
    # 苹果市净率 PB
    assert data["pb"] is not None
    assert data["pb"] > 10.0
    # 苹果市值万亿美元级别 (> 2000 亿)
    assert data["market_cap_billion"] is not None
    assert data["market_cap_billion"] > 2000.0
