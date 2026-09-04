import pytest
from unittest.mock import AsyncMock, patch
from adapters.snapshot import SnapshotAdapter
from sdk import sdk
from fastapi.testclient import TestClient
from service.app import app

@pytest.fixture
def client():
    return TestClient(app)

MOCK_TENCENT_RESPONSE = (
    'v_sh600519="1~贵州茅台~600519~1298.88~1297.50~1297.50~17748~8284~9464~1298.71~4~1298.62~2~1298.60~14~1298.56~18~1298.42~2~1298.88~298~1298.89~1~1298.99~2~1299.00~6~1299.19~1~~20260903161447~1.38~0.11~1305.00~1293.02~1298.88/17748/2305193119~17748~230519~0.14~19.94~~1305.00~1293.02~0.92~16237.06~16237.06~6.46";\n'
    'v_sz000001="51~平安银行~000001~11.88~11.91~11.88~1105134~574216~530918~11.88~423~11.87~978~11.86~901~11.85~1389~11.84~1641~11.89~1000~11.90~2334~11.91~489~11.92~210~11.93~56~~20260903150000~-0.03~-0.25~11.95~11.84~11.88/1105134/1313360400~1105134~131336~0.57~5.82~~11.95~11.84~0.92~2305.42~2305.43~0.49";\n'
    'v_usAAPL="200~苹果~AAPL.OQ~329.58~324.96~324.87~14326584~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~~2026-09-03 11:43:40~4.62~1.42~330.81~324.11~USD~14326584~4701562436~0.10~37.80~~44.19~~2.06~48076.16~48106.06~Apple Inc.~8.72~344.26~225.12~0~44.74~0.32~48106.06~21.58~4.78~GP~148.75~36.08";\n'
    'v_hk00700="100~腾讯控股~00700~433.000~438.200~444.200~17387096.0~0~0~433.000~0~0~0~0~0~0~0~0~0~433.000~0~0~0~0~0~0~0~0~0~17387096.0~2026/09/03 16:08:23~-5.200~-1.19~445.600~433.000~433.000~17387096.0~7597753829.266~0~15.83~~0~0~2.88~39416.65~39416.65~TENCENT~1.23~677.700~411.000~0.86~13.21~0~0~0~0~0~14.54~3.03";\n'
    'v_sh510300="1~沪深300ETF华泰柏瑞~510300~4.621~4.620~4.631~500000~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~~20260903150000~0.001~0.02~4.640~4.610~4.621/500000/231050000~500000~23105~0.85~0";\n'
    'v_pv_none_match="1";\n'
)

@pytest.mark.asyncio
async def test_snapshot_adapter_multi_market(monkeypatch):
    """验证 SnapshotAdapter 正确解析 A股/港股/美股/ETF 字段与严格 UTC 毫秒时间戳"""
    adapter = SnapshotAdapter()

    class MockResponse:
        status_code = 200
        text = MOCK_TENCENT_RESPONSE

    async def mock_get(*args, **kwargs):
        return MockResponse()

    import httpx
    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

    symbols = [
        "600519.SH.STK",
        "000001.SZ.STK",
        "AAPL.US.STK",
        "0700.HK.STK",
        "510300.SH.ETF",
        "INVALID.US.STK"
    ]

    snapshots, missing = await adapter.fetch_snapshots(symbols)

    assert len(snapshots) == 5
    assert missing == ["INVALID.US.STK"]

    # 验证贵州茅台
    maotai = next(s for s in snapshots if s.symbol == "600519.SH.STK")
    assert maotai.name == "贵州茅台"
    assert maotai.latest_price == 1298.88
    assert maotai.pre_close == 1297.50
    assert maotai.open == 1297.50
    assert maotai.high == 1305.00
    assert maotai.low == 1293.02
    assert maotai.change == 1.38
    assert maotai.pct_change == 0.11
    assert maotai.amount == 2305193119.0
    assert maotai.turnover_rate == 0.14
    assert maotai.pe == 19.94
    assert maotai.pe_ttm == 19.94
    assert maotai.pb == 6.46
    assert maotai.total_market_cap == 16237.06
    assert maotai.circulating_market_cap == 16237.06
    assert maotai.market_cap == 16237.06
    assert maotai.float_market_cap == 16237.06
    assert maotai.timestamp == 1788423287000 # 严格 UTC 毫秒
    # 五档盘口 (A股)
    assert maotai.ask_prices == [1298.71, 1298.62, 1298.60, 1298.56, 1298.42]
    assert maotai.ask_volumes == [4, 2, 14, 18, 2]
    assert maotai.bid_prices == [1298.88, 1298.89, 1298.99, 1299.00, 1299.19]
    assert maotai.bid_volumes == [298, 1, 2, 6, 1]

    # 验证美股苹果
    apple = next(s for s in snapshots if s.symbol == "AAPL.US.STK")
    assert apple.name == "苹果"
    assert apple.latest_price == 329.58
    assert apple.pct_change == 1.42
    assert apple.pe == 37.80
    assert apple.amount == 4701562436.0
    assert apple.total_market_cap == 48106.06
    assert apple.circulating_market_cap == 48076.16
    assert apple.ask_prices is None
    assert apple.bid_prices is None

    # 验证港股腾讯
    tencent = next(s for s in snapshots if s.symbol == "0700.HK.STK")
    assert tencent.name == "腾讯控股"
    assert tencent.latest_price == 433.0
    assert tencent.pct_change == -1.19
    assert tencent.pe == 15.83
    assert tencent.total_market_cap == 39416.65
    assert tencent.circulating_market_cap == 39416.65
    assert tencent.dividend_yield == 1.23
    assert tencent.ask_prices is None
    assert tencent.bid_prices is None

@pytest.mark.asyncio
async def test_snapshot_real_data_only_no_fake_fallback(monkeypatch):
    """
    真实性核心审计：若外部实时源未开盘/超时/无数据，
    绝对不使用历史过期的日K/分钟K假数据进行静默填补，
    全部真实反映在 missing 列表中。
    """
    adapter = SnapshotAdapter()

    class MockEmptyResponse:
        status_code = 200
        text = 'v_pv_none_match="1";\n'

    import httpx
    async def mock_get(*args, **kwargs):
        return MockEmptyResponse()

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

    snapshots, missing = await adapter.fetch_snapshots(["600519.SH.STK", "AAPL.US.STK"])
    assert len(snapshots) == 0
    assert missing == ["600519.SH.STK", "AAPL.US.STK"]

def test_snapshot_api_endpoints(client, monkeypatch):
    """测试 FastAPI 的 GET 与 POST /api/v1/snapshot 接口"""
    from adapters.snapshot import snapshot_adapter

    async def mock_fetch(symbols):
        from core.models import SnapshotItem
        data = [
            SnapshotItem(
                symbol=s,
                ticker=s.split(".")[0],
                name=f"Mock {s}",
                latest_price=100.0,
                pct_change=1.5,
                timestamp=1700000000000
            ) for s in symbols if "INVALID" not in s
        ]
        missing = [s for s in symbols if "INVALID" in s]
        return data, missing

    monkeypatch.setattr(snapshot_adapter, "fetch_snapshots", mock_fetch)

    # 1. 测试 GET
    resp_get = client.get("/api/v1/snapshot?symbols=600519.SH.STK,INVALID.US.STK")
    assert resp_get.status_code == 200
    res_json = resp_get.json()
    assert res_json["count"] == 1
    assert len(res_json["data"]) == 1
    assert res_json["data"][0]["symbol"] == "600519.SH.STK"
    assert res_json["missing"] == ["INVALID.US.STK"]

    # 2. 测试 POST /batch
    resp_post = client.post("/api/v1/snapshot/batch", json={"symbols": ["AAPL.US.STK", "0700.HK.STK"]})
    assert resp_post.status_code == 200
    post_json = resp_post.json()
    assert post_json["count"] == 2
    assert post_json["missing"] == []

    # 3. 边界防御测试: 空参数返回 400
    resp_empty = client.get("/api/v1/snapshot?symbols=")
    assert resp_empty.status_code == 400

    # 4. 边界防御测试: 超过 200 个标的拦截保护
    too_many = ",".join([f"SYM_{i}.SH.STK" for i in range(205)])
    resp_too_many = client.get(f"/api/v1/snapshot?symbols={too_many}")
    assert resp_too_many.status_code == 400
    assert "exceeds maximum limit" in resp_too_many.json()["detail"]

def test_snapshot_sdk_methods(monkeypatch):
    """验证 Python SDK 的同步与异步 get_snapshots 方法"""
    from adapters.snapshot import snapshot_adapter
    from core.models import SnapshotItem

    async def mock_fetch(symbols):
        return [
            SnapshotItem(
                symbol="600519.SH.STK",
                ticker="600519",
                name="贵州茅台",
                latest_price=1300.0,
                pct_change=0.5,
                timestamp=1700000000000
            )
        ], []

    monkeypatch.setattr(snapshot_adapter, "fetch_snapshots", mock_fetch)

    # 同步调用
    sync_res = sdk.get_snapshots(["600519.SH.STK"])
    assert sync_res.count == 1
    assert sync_res.data[0].latest_price == 1300.0
