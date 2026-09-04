import pytest
from fastapi.testclient import TestClient
from service.app import app

pytestmark = pytest.mark.live

@pytest.fixture
def client():
    return TestClient(app)

def test_market_moneyflow_real(client):
    """测试真实北向资金与互联互通资金流向"""
    resp = client.get("/api/v1/market/moneyflow")
    assert resp.status_code == 200
    data = resp.json()
    assert "date" in data
    assert data["count"] >= 2
    plates = [item["plate"] for item in data["data"]]
    assert "沪股通" in plates
    assert "深股通" in plates

def test_index_constituents_csi300_real(client):
    """测试真实沪深300指数成分股股票池"""
    resp = client.get("/api/v1/index/constituents?index_symbol=000300")
    assert resp.status_code == 200
    data = resp.json()
    assert data["index_symbol"] == "000300.SH.IDX"
    assert data["count"] == 300
    symbols = [item["symbol"] for item in data["constituents"]]
    assert len(symbols) == 300
    # 验证代码全部为规范格式
    assert all(s.endswith(".SH.STK") or s.endswith(".SZ.STK") for s in symbols)

def test_screener_real(client):
    """测试真实全市场每日截面选股器"""
    resp = client.get("/api/v1/screener?min_pct_change=0.0&limit=10")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] > 0
    first_item = data["data"][0]
    assert "symbol" in first_item
    assert "latest_price" in first_item
    assert "pct_change" in first_item
    assert first_item["latest_price"] > 0
