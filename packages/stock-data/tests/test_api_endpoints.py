import pytest
from fastapi.testclient import TestClient
from service.app import app
from core.database import meta_db
from core.models import SymbolInfo, Market, AssetType

@pytest.fixture
def client():
    return TestClient(app)

def test_root_endpoint(client):
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "online"

def test_meta_symbols_endpoint(client):
    # 先插入一个基准标的
    meta_db.upsert_symbol(SymbolInfo(
        symbol="SPX.US.IDX",
        ticker="SPX",
        market=Market.US,
        asset_type=AssetType.INDEX,
        name="S&P 500 Index",
        currency="USD",
        is_benchmark=True
    ))

    response = client.get("/api/v1/meta/symbols?market=US")
    assert response.status_code == 200
    symbols = response.json()
    assert any(s["symbol"] == "SPX.US.IDX" for s in symbols)

def test_system_storage_endpoint(client):
    response = client.get("/api/v1/system/storage")
    assert response.status_code == 200
    data = response.json()
    assert "cache_size_gb" in data
    assert "cache_max_gb" in data
    assert data["cache_max_gb"] == 20.0 # 验证硬限额配置

@pytest.mark.live
def test_kline_api_real_fetch(client):
    # 请求真实美股 AAPL 日K
    response = client.get("/api/v1/kline?symbol=AAPL.US.STK&start=2024-01-01&end=2024-01-15&adjust=raw")
    assert response.status_code == 200
    data = response.json()
    assert data["symbol"] == "AAPL.US.STK"
    assert data["period"] == "1d"
    assert len(data["data"]) > 0
    # 验证数据点字段
    first_pt = data["data"][0]
    assert "timestamp" in first_pt
    assert "open" in first_pt
    assert "close" in first_pt
    assert first_pt["close"] > 100.0

def test_kline_invalid_date_range_returns_400(client):
    """验证当 start > end 时，API 严格返回 HTTP 400 Bad Request"""
    response = client.get("/api/v1/kline?symbol=AAPL.US.STK&start=2024-05-10&end=2024-05-01")
    assert response.status_code == 400
    assert "cannot be later than end date" in response.json()["detail"]

def test_kline_minute_range_protection_returns_400(client):
    """验证当请求超长分钟K线 (>90天) 时，API 进行资源保护并返回 HTTP 400"""
    response = client.get("/api/v1/kline?symbol=AAPL.US.STK&period=1m&start=2024-01-01&end=2024-06-01")
    assert response.status_code == 400
    assert "exceeds maximum safe limit" in response.json()["detail"]

def test_kline_api_week_month_year_synthesis(client, monkeypatch):
    """验证通过 API 查询周K (1w)、月K (1M)、年K (1Y) 时能正确基于日K动态聚合返回"""
    import polars as pl
    from storage.parquet_manager import parquet_mgr

    mock_df = pl.DataFrame({
        "timestamp": [1704182400000, 1704268800000, 1707120000000], # 2024-01-02, 2024-01-03, 2024-02-05
        "open": [10.0, 10.5, 12.0],
        "high": [11.0, 11.2, 12.5],
        "low": [9.9, 10.2, 11.8],
        "close": [10.8, 10.7, 12.2],
        "volume": [100.0, 120.0, 200.0],
        "amount": [1000.0, 1200.0, 2400.0],
        "factor": [1.0, 1.0, 1.1],
        "nav": [None, None, None]
    })

    async def mock_get_or_fetch(*args, **kwargs):
        return mock_df

    monkeypatch.setattr(parquet_mgr, "get_or_fetch", mock_get_or_fetch)

    # 1. 验证周K (1w)
    resp_w = client.get("/api/v1/kline?symbol=600519.SH.STK&period=1w&start=2024-01-01&end=2024-02-10")
    assert resp_w.status_code == 200
    data_w = resp_w.json()
    assert data_w["period"] == "1w"
    assert len(data_w["data"]) == 2

    # 2. 验证月K (1M)
    resp_m = client.get("/api/v1/kline?symbol=600519.SH.STK&period=1M&start=2024-01-01&end=2024-02-10")
    assert resp_m.status_code == 200
    data_m = resp_m.json()
    assert data_m["period"] == "1M"
    assert len(data_m["data"]) == 2

    # 3. 验证年K (1Y)
    resp_y = client.get("/api/v1/kline?symbol=600519.SH.STK&period=1Y&start=2024-01-01&end=2024-02-10")
    assert resp_y.status_code == 200
    data_y = resp_y.json()
    assert data_y["period"] == "1Y"
    assert len(data_y["data"]) == 1


