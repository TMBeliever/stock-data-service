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


def test_valuation_analysis_comprehensive(client):
    """测试全谱系多维估值引擎分析接口 (/api/v1/stock/valuation/analysis)"""
    # 1. A股白马 (贵州茅台)
    resp = client.get("/api/v1/stock/valuation/analysis?symbol=600519&window=3y")
    assert resp.status_code == 200
    d_a = resp.json()
    assert d_a["status"] == "success"
    assert d_a["sample_count"] > 0
    assert d_a["latest"]["pe_ttm"] is not None
    assert d_a["latest"]["pe_ttm"]["current"] > 0
    assert len(d_a["history"]) > 0
    assert any(h.get("close") is not None for h in d_a["history"])

    # 2. 窗口切换验证 (1y vs 3y 样本量和统计值必然不同)
    resp_1y = client.get("/api/v1/stock/valuation/analysis?symbol=600519&window=1y")
    assert resp_1y.status_code == 200
    d_1y = resp_1y.json()
    assert d_1y["sample_count"] < d_a["sample_count"]

    # 3. 避险资产黄金ETF (纯价格通道，无企业PE)
    resp_gold = client.get("/api/v1/stock/valuation/analysis?symbol=518880&window=3y")
    assert resp_gold.status_code == 200
    d_gold = resp_gold.json()
    assert d_gold["status"] == "success"
    assert d_gold["latest"]["pe_ttm"] is None
    assert d_gold["latest"]["price_channel"] is not None
    assert d_gold["latest"]["price_channel"]["p20"] > 0
    assert d_gold["latest"]["price_channel"]["p80"] > d_gold["latest"]["price_channel"]["p20"]

    # 4. 跨境ETF (纳斯达克100)
    resp_ndx = client.get("/api/v1/stock/valuation/analysis?symbol=513100&window=3y")
    assert resp_ndx.status_code == 200
    d_ndx = resp_ndx.json()
    assert d_ndx["status"] == "success"
    assert d_ndx["latest"]["pe_ttm"] is not None
