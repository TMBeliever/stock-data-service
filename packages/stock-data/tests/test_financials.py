import pytest
from fastapi.testclient import TestClient
from service.app import app

@pytest.fixture
def client():
    return TestClient(app)

@pytest.mark.live
def test_financials_ashare_real(client):
    """测试真实 A 股深度财报与比率 (比亚迪 002594)"""
    resp = client.get("/api/v1/stock/financials?symbol=002594&limit=3")
    assert resp.status_code == 200
    data = resp.json()
    assert data["symbol"] == "002594.SZ.STK"
    assert data["currency"] == "CNY"
    assert data["count"] >= 1
    
    first_report = data["reports"][0]
    assert "report_date" in first_report
    # 比亚迪单季度营收高于 1000 亿
    assert first_report["revenue"] is not None
    assert first_report["revenue"] > 1e11
    # 净利润为正
    assert first_report["net_profit"] is not None
    assert first_report["net_profit"] > 0
    # 总资产高于 5000 亿
    assert first_report["total_assets"] is not None
    assert first_report["total_assets"] > 5e11
    # 资产负债率合理
    assert first_report["debt_to_asset_pct"] is not None
    assert 40.0 < first_report["debt_to_asset_pct"] < 90.0

@pytest.mark.live
def test_financials_us_real(client):
    """测试真实美股深度财报 (苹果 AAPL)"""
    resp = client.get("/api/v1/stock/financials?symbol=AAPL&limit=2")
    assert resp.status_code == 200
    data = resp.json()
    assert data["symbol"] == "AAPL.US.STK"
    assert data["currency"] == "USD"
    assert data["count"] >= 1
    
    first_report = data["reports"][0]
    assert first_report["revenue"] is not None
    assert first_report["revenue"] > 1e10 # 苹果单季营收 > 100 亿美元
    assert first_report["net_profit"] is not None
    assert first_report["net_profit"] > 0

@pytest.mark.live
def test_financials_point_in_time_ashare(client):
    """测试 Point-in-Time 回测无未来函数过滤 (as_of 严格过滤披露日)"""
    # 模拟在 2024-05-01 时点回测贵州茅台 (600519)
    # 在 2024-05-01 之后披露的 2024 中报、三季报绝不能返回
    as_of_date = "2024-05-01"
    resp = client.get(f"/api/v1/stock/financials?symbol=600519&as_of={as_of_date}&limit=5")
    assert resp.status_code == 200
    data = resp.json()
    assert data["as_of"] == as_of_date
    assert data["count"] >= 1
    for r in data["reports"]:
        # 每一个返回的报表，披露日必须 <= as_of_date (若有公告日) 且报告日 <= as_of_date
        effective_date = r.get("announcement_date") or r.get("report_date")
        assert effective_date <= as_of_date, f"Look-ahead bias detected! {effective_date} > {as_of_date}"

def test_strict_pit_disallows_missing_announcement_date(client, monkeypatch):
    """测试严格 Point-in-Time 逻辑：当财报公告披露日为空时，绝不假设报告期末即为已知，必须排除"""
    import pandas as pd
    from service.routes import financials

    df_lrb = pd.DataFrame([{
        "报告日": "2023-12-31",
        "公告日期": None,
        "营业总收入": 1000000.0,
        "净利润": 200000.0,
        "营业总成本": 700000.0
    }])
    df_fzb = pd.DataFrame([{
        "报告日": "2023-12-31",
        "资产总计": 5000000.0,
        "负债合计": 2000000.0
    }])
    df_llb = pd.DataFrame([{
        "报告日": "2023-12-31",
        "经营活动产生的现金流量净额": 300000.0
    }])

    async def mock_fetch(code):
        return df_lrb, df_fzb, df_llb

    monkeypatch.setattr(financials, "_fetch_sina_reports", mock_fetch)

    resp = client.get("/api/v1/stock/financials?symbol=600000.SH.STK&as_of=2024-05-01")
    assert resp.status_code == 200
    data = resp.json()
    assert data["pit_status"] == "STRICT"
    # 公告日缺失时必须排除，杜绝前视偏差
    assert data["count"] == 0
    assert len(data["reports"]) == 0

def test_us_financials_reports_estimated_pit_status(client, monkeypatch):
    """Test F: 验证海外美股财报在指定 as_of 时，系统诚实返回 pit_status='ESTIMATED'，绝不冒充 'STRICT'"""
    import pandas as pd
    import service.routes.financials as fin_mod

    col = pd.Timestamp("2023-12-31")
    mock_fin = pd.DataFrame(
        {col: [100000000.0, 20000000.0]},
        index=["Total Revenue", "Net Income"]
    )
    mock_bs = pd.DataFrame(
        {col: [500000000.0, 200000000.0]},
        index=["Total Assets", "Total Liabilities Net Minority Interest"]
    )
    mock_cf = pd.DataFrame(
        {col: [30000000.0]},
        index=["Operating Cash Flow"]
    )

    class MockTicker:
        def __init__(self, t):
            self.quarterly_financials = mock_fin
            self.quarterly_balance_sheet = mock_bs
            self.quarterly_cashflow = mock_cf
            self.info = {}

    # 必须 patch 路由模块里的 yf.Ticker，而不是 yfinance 全局对象
    monkeypatch.setattr(fin_mod.yf, "Ticker", MockTicker)

    # 1. 传入 as_of="2024-05-01"，因为海外源没有公告披露日，系统自动标记为 ESTIMATED
    resp = client.get("/api/v1/stock/financials?symbol=AAPL.US.STK&as_of=2024-05-01")
    assert resp.status_code == 200
    data = resp.json()
    assert data["pit_status"] == "ESTIMATED"
    assert data["pit_status"] != "STRICT", "Overseas financials must not falsely pretend to be STRICT PIT!"
    assert data["count"] == 1
    assert data["reports"][0]["announcement_date"] is None

    # 2. 未传 as_of 时，状态为 UNAVAILABLE
    resp_no_asof = client.get("/api/v1/stock/financials?symbol=AAPL.US.STK")
    assert resp_no_asof.status_code == 200
    data_no_asof = resp_no_asof.json()
    assert data_no_asof["pit_status"] == "UNAVAILABLE"


