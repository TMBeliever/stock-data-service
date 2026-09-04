import pytest
from fastapi.testclient import TestClient
from service.app import app

pytestmark = pytest.mark.live

@pytest.fixture
def client():
    return TestClient(app)

def test_company_profile_real(client):
    """测试真实公司画像与行业分类 (比亚迪 002594 & 苹果 AAPL)"""
    resp_cn = client.get("/api/v1/stock/profile?symbol=002594")
    assert resp_cn.status_code == 200
    data_cn = resp_cn.json()
    assert data_cn["symbol"] == "002594.SZ.STK"
    assert "比亚迪" in data_cn["company_name"]
    assert "汽车" in data_cn["industry"]
    assert data_cn["listing_date"] == "2011-06-30"

    resp_us = client.get("/api/v1/stock/profile?symbol=AAPL")
    assert resp_us.status_code == 200
    data_us = resp_us.json()
    assert data_us["symbol"] == "AAPL.US.STK"
    assert "Apple" in data_us["company_name"]
    assert "Technology" in data_us["industry"] or len(data_us["industry"]) > 0

def test_shareholders_real(client):
    """测试真实十大流通股东与筹码集中度 (比亚迪 002594)"""
    resp = client.get("/api/v1/stock/shareholders?symbol=002594")
    assert resp.status_code == 200
    data = resp.json()
    assert data["symbol"] == "002594.SZ.STK"
    assert data["total_shareholders"] is not None
    assert data["total_shareholders"] > 100000 # 股东数超过 10 万户
    assert len(data["top_holders"]) >= 5
    first_holder = data["top_holders"][0]
    assert "name" in first_holder
    assert first_holder["rank"] == 1

def test_market_sectors_real(client):
    """测试真实全市场行业热点排行"""
    resp = client.get("/api/v1/market/sectors?indicator=行业&limit=5")
    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "行业"
    assert data["count"] > 0
    first_sector = data["data"][0]
    assert "sector_name" in first_sector
    assert "pct_change" in first_sector
    assert "leading_stock" in first_sector

def test_dragon_tiger_real(client):
    """测试每日龙虎榜真实数据"""
    resp = client.get("/api/v1/market/dragon-tiger")
    assert resp.status_code == 200
    data = resp.json()
    assert "date" in data
    assert "count" in data
    if data["count"] > 0:
        first_item = data["data"][0]
        assert "symbol" in first_item
        assert "reason" in first_item

def test_treasury_yield_real(client):
    """测试中美国债收益率基准"""
    resp = client.get("/api/v1/macro/treasury-yield")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["data"]) >= 1
    us_yield = [x for x in data["data"] if x["code"] == "US10Y"]
    if us_yield:
        assert 2.0 < us_yield[0]["latest_yield"] < 8.0
