import pytest
from unittest.mock import AsyncMock
import polars as pl
from sdk import StockDataSDK

def test_sdk_sync_in_sync_environment(monkeypatch):
    """验证 sync SDK 在标准同步环境下正常工作"""
    sdk = StockDataSDK()
    mock_df = pl.DataFrame({
        "timestamp": [1704182400000],
        "open": [10.0], "high": [10.0], "low": [10.0], "close": [10.0],
        "volume": [100.0], "amount": [1000.0], "factor": [1.0], "nav": [None]
    })
    monkeypatch.setattr(sdk, "get_kline_async", AsyncMock(return_value=mock_df))

    df = sdk.get_kline("600519.SH.STK", period="1d", start="2024-01-01", end="2024-01-05")
    assert df is not None
    assert len(df) == 1

@pytest.mark.asyncio
async def test_sdk_sync_in_running_event_loop(monkeypatch):
    """验证 sync SDK 在已有运行中的事件循环中 (如 Jupyter / FastAPI / 异步测试) 调用不会报 RuntimeError 且正常返回"""
    sdk = StockDataSDK()
    mock_df = pl.DataFrame({
        "timestamp": [1704182400000],
        "open": [10.0], "high": [10.0], "low": [10.0], "close": [10.0],
        "volume": [100.0], "amount": [1000.0], "factor": [1.0], "nav": [None]
    })
    monkeypatch.setattr(sdk, "get_kline_async", AsyncMock(return_value=mock_df))

    # 在当前运行的 async event loop 中直接调用同步方法 get_kline
    df = sdk.get_kline("600519.SH.STK", period="1d", start="2024-01-01", end="2024-01-05")
    assert df is not None
    assert len(df) == 1
