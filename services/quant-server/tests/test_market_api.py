import pytest
from fastapi.testclient import TestClient
from quant_server.main import app

client = TestClient(app)

def test_search_symbols_empty():
    """测试未传关键字时返回热门精选标的"""
    resp = client.get("/api/v1/market/symbols/search?limit=10")
    assert resp.status_code == 200
    data = resp.json()
    assert "count" in data
    assert len(data["data"]) > 0
    # 验证字段完备性
    first = data["data"][0]
    assert "symbol" in first
    assert "ticker" in first
    assert "name" in first
    assert "market" in first
    assert "asset_type" in first

def test_search_symbols_by_code():
    """测试按股票/ETF代码检索"""
    resp = client.get("/api/v1/market/symbols/search?q=600519")
    assert resp.status_code == 200
    data = resp.json()
    symbols = [item["symbol"] for item in data["data"]]
    assert any("600519" in s for s in symbols)

def test_search_symbols_by_pinyin():
    """测试按拼音简写检索 (如 GZMT 贵州茅台)"""
    resp = client.get("/api/v1/market/symbols/search?q=GZMT")
    assert resp.status_code == 200
    data = resp.json()
    names = [item["name"] for item in data["data"]]
    assert any("茅台" in n for n in names)

def test_search_symbols_by_chinese():
    """测试按中文模糊检索 (如 沪深300 / 宁德)"""
    resp = client.get("/api/v1/market/symbols/search?q=沪深300")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["data"]) > 0
    assert any("沪深300" in item["name"] for item in data["data"])

def test_get_symbol_detail():
    """测试获取单标的详情与行情快照"""
    resp = client.get("/api/v1/market/symbols/600519.SH.STK/detail")
    assert resp.status_code == 200
    data = resp.json()
    assert data["symbol"] == "600519.SH.STK"
    assert "detail" in data
    assert "latest_price" in data["detail"]

def test_get_symbol_kline():
    """测试获取单标的日K线与均线计算"""
    resp = client.get("/api/v1/market/symbols/600519.SH.STK/kline?limit=30")
    assert resp.status_code == 200
    data = resp.json()
    assert data["symbol"] == "600519.SH.STK"
    assert "data" in data
    if data["data"]:
        bar0 = data["data"][-1]
        assert "open" in bar0
        assert "close" in bar0
        assert "high" in bar0
        assert "low" in bar0
        assert "volume" in bar0
        assert "date" in bar0
