import pytest
import datetime
from core.models import SymbolInfo, Market, AssetType, KlinePeriod
from adapters.cn_akshare import AkShareAdapter
from adapters.global_yfinance import YFinanceAdapter

# 注意：根据用户AI规范，所有测试必须采用真实数据源拉取，严禁捏造数据。
pytestmark = pytest.mark.live

@pytest.mark.asyncio
async def test_yfinance_real_stock_daily():
    """测试真实美股股票历史日K拉取 (苹果 AAPL)"""
    adapter = YFinanceAdapter()
    info = SymbolInfo(
        symbol="AAPL.US.STK",
        ticker="AAPL",
        market=Market.US,
        asset_type=AssetType.STOCK,
        name="Apple Inc.",
        currency="USD"
    )
    # 拉取 2024 年真实数据
    df = adapter.fetch_daily(info, start_date="2024-01-01", end_date="2024-01-31")
    assert df is not None
    assert not df.is_empty()
    assert "timestamp" in df.columns
    assert "close" in df.columns
    # 验证时间戳单调递增
    timestamps = df["timestamp"].to_list()
    assert timestamps == sorted(timestamps)
    # 验证价格为合理真实区间 (>100 USD)
    assert df["close"].min() > 100.0

@pytest.mark.asyncio
async def test_yfinance_real_index_and_etf():
    """测试真实全球宽基指数 (标普500) 与核心 ETF (SPY)"""
    adapter = YFinanceAdapter()
    
    # 标普500指数
    idx_info = SymbolInfo(
        symbol="SPX.US.IDX",
        ticker="SPX",
        market=Market.US,
        asset_type=AssetType.INDEX,
        name="S&P 500 Index",
        currency="USD",
        is_benchmark=True
    )
    df_idx = adapter.fetch_daily(idx_info, start_date="2024-01-01", end_date="2024-01-31")
    assert df_idx is not None
    assert not df_idx.is_empty()
    assert df_idx["close"].min() > 4000.0 # 标普真实点位高于 4000

    # 标普500 ETF (SPY)
    etf_info = SymbolInfo(
        symbol="SPY.US.ETF",
        ticker="SPY",
        market=Market.US,
        asset_type=AssetType.ETF,
        name="SPDR S&P 500 ETF",
        currency="USD",
        is_benchmark=True
    )
    df_etf = adapter.fetch_daily(etf_info, start_date="2024-01-01", end_date="2024-01-31")
    assert df_etf is not None
    assert not df_etf.is_empty()
    assert df_etf["close"].min() > 400.0

@pytest.mark.asyncio
async def test_akshare_real_ashare_stock_daily():
    """测试真实 A 股历史日K拉取 (贵州茅台 600519)"""
    adapter = AkShareAdapter()
    info = SymbolInfo(
        symbol="600519.SH.STK",
        ticker="600519",
        market=Market.SH,
        asset_type=AssetType.STOCK,
        name="贵州茅台",
        currency="CNY"
    )
    df = adapter.fetch_daily(info, start_date="2024-01-01", end_date="2024-01-31")
    assert df is not None
    assert not df.is_empty()
    assert "timestamp" in df.columns
    # 茅台真实收盘价在 1000 元以上
    assert df["close"].min() > 1000.0
    # 茅台历史多次大额分红派息，真实后复权因子远大于 1.0 (约 8.0 左右)，严禁伪造为 1.0
    assert "factor" in df.columns
    assert df["factor"].max() > 5.0

@pytest.mark.asyncio
async def test_akshare_real_broad_index_and_etf():
    """测试真实 A 股宽基指数 (沪深300 000300) 与核心 ETF (510300)"""
    adapter = AkShareAdapter()
    
    # 沪深300 指数
    idx_info = SymbolInfo(
        symbol="000300.SH.IDX",
        ticker="000300",
        market=Market.SH,
        asset_type=AssetType.INDEX,
        name="沪深300指数",
        currency="CNY",
        is_benchmark=True
    )
    df_idx = adapter.fetch_daily(idx_info, start_date="2024-01-01", end_date="2024-01-31")
    assert df_idx is not None
    assert not df_idx.is_empty()
    assert df_idx["close"].min() > 2500.0 # 沪深300真实点位

    # 300ETF (510300)
    etf_info = SymbolInfo(
        symbol="510300.SH.ETF",
        ticker="510300",
        market=Market.SH,
        asset_type=AssetType.ETF,
        name="300ETF",
        currency="CNY",
        is_benchmark=True
    )
    df_etf = adapter.fetch_daily(etf_info, start_date="2024-01-01", end_date="2024-01-31")
    assert df_etf is not None
    assert not df_etf.is_empty()
    assert df_etf["close"].min() > 2.0 # 300ETF价格区间通常在 3.x 左右

@pytest.mark.asyncio
async def test_akshare_minute_range_filter_and_factor():
    """测试真实 A 股分钟线严格日期区间过滤与复权因子对齐"""
    adapter = AkShareAdapter()
    info = SymbolInfo(
        symbol="600519.SH.STK",
        ticker="600519",
        market=Market.SH,
        asset_type=AssetType.STOCK,
        name="贵州茅台",
        currency="CNY"
    )
    # 仅请求 2024-05-10 单日
    # 若无此单日数据，fetch_minute 返回 None 或仅包含该日期的记录
    df_min = adapter.fetch_minute(info, KlinePeriod.M5, "2024-05-10", "2024-05-10")
    if df_min is not None and not df_min.is_empty():
        # 验证所有返回记录的时间戳均属于请求日期
        for ts in df_min["timestamp"]:
            dt_bj = datetime.datetime.fromtimestamp(ts / 1000, tz=datetime.timezone(datetime.timedelta(hours=8)))
            assert dt_bj.strftime("%Y-%m-%d") == "2024-05-10"
        # 验证包含 factor 列
        assert "factor" in df_min.columns

