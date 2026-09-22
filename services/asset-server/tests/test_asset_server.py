import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.pool import StaticPool
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from asset_server.main import app
from asset_server.database import Base, get_db
import asset_server.models  # noqa: F401
from asset_server.providers.mock import MockMarketDataProvider
from asset_server.providers.factory import set_market_data_provider, get_market_data_provider
from asset_server.config import settings

# 测试专用内存 SQLite
test_engine = create_async_engine(
    "sqlite+aiosqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = async_sessionmaker(
    bind=test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def override_get_db():
    async with TestingSessionLocal() as session:
        yield session


@pytest_asyncio.fixture(autouse=True)
async def prepare_database():
    app.dependency_overrides[get_db] = override_get_db

    # 注入 Mock 行情驱动器 (确定性价格)
    set_market_data_provider(MockMarketDataProvider({
        "510300.SH.ETF": {"price": 4.582, "prev_close": 4.532, "change_pct": 1.10},
        "510880.SH.ETF": {"price": 3.339, "prev_close": 3.347, "change_pct": -0.24},
        "600519.SH": {"price": 1560.00, "prev_close": 1540.00, "change_pct": 1.30},
    }))

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_asset_server_health():
    """验证健康检查端点"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "healthy", "service": "asset-server"}


@pytest.mark.asyncio
async def test_full_asset_lifecycle_and_net_worth():
    """
    全流程端到端测试：
    1. 录入多大类资产 (现金、股票ETF、房产、房贷负债)；
    2. 验证动态核算 (总资产、总负债、真实净资产 = 总资产 - 负债)；
    3. 验证股票行情联动 (现价与浮动盈亏计算)；
    4. 验证大类资产分类筛选；
    5. 验证资产修改与删除。
    """
    transport = ASGITransport(app=app)
    headers = {"x-user-id": "1001"}

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # 1. 初始概览为空
        overview_resp = await client.get("/api/v1/asset/overview", headers=headers)
        assert overview_resp.status_code == 200
        assert overview_resp.json()["summary"]["net_worth"] == 0.0

        # 2. 录入现金资产 (50,000 元)
        cash_resp = await client.post(
            "/api/v1/asset/items",
            headers=headers,
            json={
                "category": "CASH",
                "name": "招商银行活期存款",
                "amount": 50000.0,
                "cost_price": 1.0,
                "note": "日常备用金",
            },
        )
        assert cash_resp.status_code == 200
        cash_id = cash_resp.json()["data"]["id"]

        # 3. 录入股票 ETF (10,000 份 沪深300 ETF，买入均价 3.75，Mock 现价 4.582)
        stock_resp = await client.post(
            "/api/v1/asset/items",
            headers=headers,
            json={
                "category": "EQUITY",
                "name": "沪深300 ETF",
                "symbol": "510300.SH.ETF",
                "amount": 10000.0,
                "cost_price": 3.75,
                "note": "宽基定投核心底仓",
            },
        )
        assert stock_resp.status_code == 200
        stock_data = stock_resp.json()["data"]
        assert stock_data["current_price"] == 4.582
        assert stock_data["market_value"] == 45820.0
        assert stock_data["unrealized_pnl"] == 8320.0
        assert stock_data["unrealized_pnl_pct"] == 22.19
        stock_id = stock_data["id"]

        # 4. 录入房产资产 (手动估值 3,000,000 元)
        house_resp = await client.post(
            "/api/v1/asset/items",
            headers=headers,
            json={
                "category": "REAL_ESTATE",
                "name": "自住房产",
                "amount": 1.0,
                "manual_price": 3000000.0,
                "cost_price": 2600000.0,
                "note": "首套自住",
            },
        )
        assert house_resp.status_code == 200

        # 5. 录入房贷负债 (800,000 元)
        debt_resp = await client.post(
            "/api/v1/asset/items",
            headers=headers,
            json={
                "category": "LIABILITY",
                "name": "银行房贷按揭余额",
                "amount": 800000.0,
                "cost_price": 1.0,
                "note": "公积金与商业组合贷",
            },
        )
        assert debt_resp.status_code == 200

        # 6. 查询全景资产总览并验证净资产核算
        overview_resp2 = await client.get("/api/v1/asset/overview", headers=headers)
        assert overview_resp2.status_code == 200
        summary = overview_resp2.json()["summary"]
        categories = overview_resp2.json()["categories"]

        expected_assets = round(50000.0 + 45820.0 + 3000000.0, 2)  # 3,095,820.0
        expected_liabilities = 800000.0
        expected_net_worth = round(expected_assets - expected_liabilities, 2)  # 2,295,820.0

        assert summary["total_assets"] == expected_assets
        assert summary["total_liabilities"] == expected_liabilities
        assert summary["net_worth"] == expected_net_worth
        assert summary["item_count"] == 4

        # 验证大类占比存在
        cat_names = [c["category"] for c in categories]
        assert "CASH" in cat_names
        assert "EQUITY" in cat_names
        assert "REAL_ESTATE" in cat_names
        assert "LIABILITY" in cat_names

        # 7. 按大类筛选
        list_equity_resp = await client.get("/api/v1/asset/items?category=EQUITY", headers=headers)
        assert list_equity_resp.status_code == 200
        equity_items = list_equity_resp.json()["items"]
        assert len(equity_items) == 1
        assert equity_items[0]["symbol"] == "510300.SH.ETF"

        # 8. 修改资产 (修改现金金额)
        update_resp = await client.put(
            f"/api/v1/asset/items/{cash_id}",
            headers=headers,
            json={"amount": 60000.0},
        )
        assert update_resp.status_code == 200
        assert update_resp.json()["data"]["market_value"] == 60000.0

        # 9. 越权修改不存在或不属于该用户的资产返回 404
        wrong_update = await client.put(
            f"/api/v1/asset/items/{cash_id}",
            headers={"x-user-id": "9999"},
            json={"amount": 1.0},
        )
        assert wrong_update.status_code == 404

        # 10. 删除资产 (删除股票)
        del_resp = await client.delete(f"/api/v1/asset/items/{stock_id}", headers=headers)
        assert del_resp.status_code == 200

        overview_resp3 = await client.get("/api/v1/asset/overview", headers=headers)
        assert overview_resp3.json()["summary"]["item_count"] == 3


@pytest.mark.asyncio
async def test_market_provider_abstraction():
    """验证行情适配器抽象接口规范与工厂模式切换"""
    provider = MockMarketDataProvider({"CUSTOM_SYM": {"price": 99.9, "change_pct": 5.0}})
    quotes = await provider.get_batch_quotes(["CUSTOM_SYM", "UNKNOWN_SYM"])

    assert "CUSTOM_SYM" in quotes
    assert quotes["CUSTOM_SYM"].price == 99.9
    assert quotes["CUSTOM_SYM"].change_pct == 5.0

    # 未知标的安全兜底
    assert "UNKNOWN_SYM" in quotes
    assert quotes["UNKNOWN_SYM"].price == 10.0


@pytest.mark.asyncio
async def test_multi_currency_fx_valuation():
    """验证多币种外币 (USD, HKD) 资产自动折合基准本位币 (CNY) 核算"""
    transport = ASGITransport(app=app)
    headers = {"x-user-id": "2002"}

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # 录入 10,000 美元现金 (USD)
        resp1 = await client.post(
            "/api/v1/asset/items",
            headers=headers,
            json={
                "category": "CASH",
                "name": "富途美元证券现金",
                "amount": 10000.0,
                "cost_price": 1.0,
                "currency": "USD",
                "note": "美股备用金",
            },
        )
        assert resp1.status_code == 200
        usd_item = resp1.json()["data"]
        assert usd_item["currency"] == "USD"
        assert usd_item["fx_rate"] > 6.0  # 汇率大于 6
        assert usd_item["market_val_raw"] == 10000.0
        assert usd_item["market_value"] == round(10000.0 * usd_item["fx_rate"], 2)

        # 录入 100,000 人民币现金 (CNY)
        resp2 = await client.post(
            "/api/v1/asset/items",
            headers=headers,
            json={
                "category": "CASH",
                "name": "招商银行人民币活期",
                "amount": 100000.0,
                "cost_price": 1.0,
                "currency": "CNY",
            },
        )
        assert resp2.status_code == 200

        # 查询总览：总资产应为 CNY + USD折算CNY (大于 160,000 元，而不是简单相加的 110,000)
        overview_resp = await client.get("/api/v1/asset/overview", headers=headers)
        assert overview_resp.status_code == 200
        summary = overview_resp.json()["summary"]
        expected_total = round(100000.0 + round(10000.0 * usd_item["fx_rate"], 2), 2)
        assert summary["total_assets"] == expected_total
        assert summary["base_currency"] == "CNY"
        assert "USD" in summary["fx_rates"]


@pytest.mark.asyncio
async def test_internal_stock_data_provider_hk_quote():
    """验证 InternalStockDataProvider 解析 stock-data 返回的 latest_price / pre_close 字段并支持别名"""
    from unittest.mock import AsyncMock, MagicMock, patch
    from asset_server.providers.internal import InternalStockDataProvider
    from asset_server.engine.valuation import calculate_assets_valuation
    from asset_server.models import AssetItem

    provider = InternalStockDataProvider(base_url="http://mock-stock-data")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "count": 1,
        "data": [
            {
                "symbol": "00700.HK.STK",
                "ticker": "00700",
                "name": "腾讯控股",
                "latest_price": 459.8,
                "pre_close": 430.0,
                "open": 442.0,
                "pct_change": 6.93,
            }
        ],
        "missing": [],
    }

    with patch.object(provider, "_get_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_get_client.return_value = mock_client

        # 测试批量拉取 (包含标准代码和短代码)
        quotes = await provider.get_batch_quotes(["00700.HK.STK", "00700.HK"])
        assert "00700.HK.STK" in quotes
        snap = quotes["00700.HK.STK"]
        assert snap.price == 459.8
        assert snap.prev_close == 430.0
        assert snap.change_pct == 6.93

        # 别名短代码也应当能查到
        assert "00700.HK" in quotes
        assert quotes["00700.HK"].price == 459.8

    # 测试 valuation 结合汇率
    from asset_server.providers.factory import set_market_data_provider
    set_market_data_provider(provider)

    test_item = AssetItem(
        id=99,
        user_id=1,
        category="EQUITY",
        name="腾讯控股",
        symbol="00700.HK.STK",
        amount=100.0,
        cost_price=435.0,
        currency="HKD",
    )

    val = await calculate_assets_valuation([test_item])
    item_val = val["items"][0]
    assert item_val["current_price"] == 459.8
    assert item_val["market_val_raw"] == 45980.0
    assert item_val["cost_val_raw"] == 43500.0
    assert item_val["pnl_raw"] == 2480.0
    assert item_val["unrealized_pnl_pct"] > 0
    assert item_val["market_value"] > 0
    assert val["summary"]["total_assets"] > 0


