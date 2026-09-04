import pytest
from sdk import StockDataSDK

pytestmark = pytest.mark.live

@pytest.mark.asyncio
async def test_sdk_async_real_fetch():
    sdk = StockDataSDK()
    # 异步拉取标普500 ETF (SPY)
    df = await sdk.get_kline_async("SPY.US.ETF", period="1d", start="2024-01-01", end="2024-01-15")
    assert df is not None
    assert not df.is_empty()
    assert "timestamp" in df.columns
    assert "close" in df.columns
    assert df["close"].min() > 400.0

def test_sdk_sync_real_fetch():
    sdk = StockDataSDK()
    # 同步接口直接调用 (模拟标准回测策略调用)
    df = sdk.get_kline("AAPL.US.STK", period="1d", start="2024-01-01", end="2024-01-15")
    assert df is not None
    assert not df.is_empty()
    assert df["close"].min() > 100.0
