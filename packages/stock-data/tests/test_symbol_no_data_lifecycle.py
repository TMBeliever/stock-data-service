import pytest
import asyncio
import time
from pathlib import Path
import polars as pl

from core.models import SymbolInfo, Market, AssetType, KlinePeriod
from core.database import meta_db
from storage.parquet_manager import ParquetManager
from adapters.factory import adapter_factory
from adapters.base import BaseDataSource

@pytest.fixture
def clean_test_env():
    info = SymbolInfo(
        symbol="LIFECYCLE.SH.STK",
        ticker="LIFECYCLE",
        market=Market.SH,
        asset_type=AssetType.STOCK,
        name="Lifecycle Stock",
        currency="CNY",
        is_benchmark=False
    )
    pm = ParquetManager()
    path = pm.get_file_path(info, "1d")
    if path.exists():
        path.unlink()
    meta_db.remove_cache_record(info.symbol, "1d")
    meta_db.clear_symbol_no_data(info.symbol, "1d")
    with meta_db._get_conn() as conn:
        conn.execute("DELETE FROM trading_calendars WHERE trade_date >= '2030-01-01'")
        conn.commit()
    yield pm, info, path
    if path.exists():
        path.unlink()
    meta_db.remove_cache_record(info.symbol, "1d")
    meta_db.clear_symbol_no_data(info.symbol, "1d")
    with meta_db._get_conn() as conn:
        conn.execute("DELETE FROM trading_calendars WHERE trade_date >= '2030-01-01'")
        conn.commit()

def test_symbol_no_data_ttl():
    """
    P0 审计：验证 symbol_no_data 具有严格时间语义 (TTL)
    - 刚记录时处于有效期，is_symbol_no_data 返回 True
    - 超过 TTL 后自动失效，返回 False，触发后续请求重新向 Provider 验证
    """
    symbol = "TTL_TEST.SH.STK"
    trade_date = "2024-05-10"
    meta_db.clear_symbol_no_data(symbol, "1d")

    # 1. 记录空数据
    meta_db.mark_symbol_no_data(symbol, "1d", trade_date)
    assert meta_db.is_symbol_no_data(symbol, "1d", trade_date, ttl_seconds=10) is True

    # 2. 模拟 TTL 超时 (设置 ttl_seconds = 1 并 sleep 1.1s)
    time.sleep(1.1)
    assert meta_db.is_symbol_no_data(symbol, "1d", trade_date, ttl_seconds=1) is False

    meta_db.clear_symbol_no_data(symbol, "1d")

@pytest.mark.asyncio
async def test_symbol_no_data_cleared_after_success(monkeypatch, clean_test_env):
    """
    P0 审计：验证当 Provider 恢复并成功返回数据时，stale no-data 记录必须被彻底清除
    """
    pm, info, path = clean_test_env
    test_date = "2035-01-08" # 周一

    # 1. 初始状态：先人为记录该日期为 no-data
    meta_db.mark_symbol_no_data(info.symbol, "1d", test_date)
    assert meta_db.is_symbol_no_data(info.symbol, "1d", test_date) is True

    # 2. 模拟 Provider 恢复正常，返回真实有效数据
    from core.time import date_range_to_utc_boundary
    ts_start, _ = date_range_to_utc_boundary(test_date, test_date, Market.SH)
    bar_ts = ts_start + 15 * 3600 * 1000 - 8 * 3600 * 1000

    class RestoredAdapter(BaseDataSource):
        def fetch_daily(self, info, start_date, end_date):
            return pl.DataFrame({
                "timestamp": [bar_ts],
                "open": [10.0], "high": [10.0], "low": [10.0], "close": [10.0],
                "volume": [100.0], "amount": [1000.0], "factor": [1.0], "nav": [None]
            })
        def fetch_minute(self, *args, **kwargs): return None
        def fetch_snapshot(self, *args, **kwargs): return None
        def fetch_calendar(self, *args, **kwargs): return []
        def fetch_symbols(self, *args, **kwargs): return []

    monkeypatch.setattr(adapter_factory, "get_adapter", lambda m: RestoredAdapter())

    # 调用获取数据
    df = await pm.get_or_fetch(info, KlinePeriod.D1, test_date, test_date)
    assert df is not None
    assert len(df) == 1

    # 核心断言：成功获取数据后，stale no-data 记录已被彻底清理
    assert meta_db.is_symbol_no_data(info.symbol, "1d", test_date) is False
    # 全市场日历记录为 OPEN
    assert meta_db.get_calendar_status("SH", test_date) == "OPEN"

@pytest.mark.asyncio
async def test_empty_provider_does_not_close_market_and_avoids_closed_dates(monkeypatch, clean_test_env):
    """
    P0 审计：Provider Empty 绝不能推导 Market CLOSED；
    且已知 CLOSED 日期 (如周末) 不得创建冗余 symbol_no_data
    """
    pm, info, path = clean_test_env
    # 2035-01-06 (周六) 至 2035-01-08 (周一)
    class EmptyAdapter(BaseDataSource):
        def fetch_daily(self, info, start_date, end_date): return pl.DataFrame()
        def fetch_minute(self, *args, **kwargs): return None
        def fetch_snapshot(self, *args, **kwargs): return None
        def fetch_calendar(self, *args, **kwargs): return []
        def fetch_symbols(self, *args, **kwargs): return []

    monkeypatch.setattr(adapter_factory, "get_adapter", lambda m: EmptyAdapter())

    res = await pm.get_or_fetch(info, KlinePeriod.D1, "2035-01-06", "2035-01-08")
    assert res is None

    # 1. 2035-01-08 (周一工作日)：日历保持 UNKNOWN，绝不是 CLOSED
    assert meta_db.get_calendar_status("SH", "2035-01-08") == "UNKNOWN"
    # 标的级记为 no-data
    assert meta_db.is_symbol_no_data(info.symbol, "1d", "2035-01-08") is True

    # 2. 2035-01-06 (周六)：已由规则判定为非交易日 (is_trading_day is False)
    # 绝不应在 symbol_no_data 表中增加垃圾周末记录
    assert meta_db.is_symbol_no_data(info.symbol, "1d", "2035-01-06") is False

def test_metadata_matches_physical_parquet_without_stale_boundaries():
    """
    P1 审计：验证元数据绝对不撒谎原则 (Metadata == Physical Parquet)
    即使先记录大范围元数据，随后物理文件范围缩小时，元数据也必须精准缩减，绝不能因 MIN/MAX 保留过期范围
    """
    symbol = "METAMATCH.SH.STK"
    period = "1d"
    meta_db.remove_cache_record(symbol, period)

    # 1. 首次记录大范围: 2024-01-01 ~ 2024-01-30, 30 行
    meta_db.record_cache_access(
        symbol=symbol,
        period=period,
        file_path="/fake/path.parquet",
        file_size_bytes=5000,
        covered_start_date="2024-01-01",
        covered_end_date="2024-01-30",
        min_ts=1704067200000,
        max_ts=1706572800000,
        row_count=30
    )
    rec1 = meta_db.get_cache_info(symbol, period)
    assert rec1["covered_start_date"] == "2024-01-01"
    assert rec1["covered_end_date"] == "2024-01-30"
    assert rec1["row_count"] == 30

    # 2. 文件截断或重新生成小范围: 2024-01-10 ~ 2024-01-15, 5 行
    meta_db.record_cache_access(
        symbol=symbol,
        period=period,
        file_path="/fake/path.parquet",
        file_size_bytes=1000,
        covered_start_date="2024-01-10",
        covered_end_date="2024-01-15",
        min_ts=1704844800000,
        max_ts=1705276800000,
        row_count=5
    )
    rec2 = meta_db.get_cache_info(symbol, period)
    # 核心断言：元数据必须与最新物理写入保持 100% 一致，严禁保留已不存在的历史范围
    assert rec2["covered_start_date"] == "2024-01-10"
    assert rec2["covered_end_date"] == "2024-01-15"
    assert rec2["row_count"] == 5

    meta_db.remove_cache_record(symbol, period)
