import pytest
import asyncio
import os
import time
from pathlib import Path
from unittest.mock import patch
import polars as pl

from core.models import SymbolInfo, Market, AssetType, KlinePeriod
from core.database import meta_db
from core.lock import SingleFlightLock
from storage.parquet_manager import ParquetManager
from adapters.factory import adapter_factory
from adapters.base import BaseDataSource

@pytest.fixture
def clean_test_env():
    info = SymbolInfo(
        symbol="FAILTEST.SH.STK",
        ticker="FAILTEST",
        market=Market.SH,
        asset_type=AssetType.STOCK,
        name="Fail Test Stock",
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

@pytest.mark.asyncio
async def test_provider_failure_does_not_pollute_calendar_or_stuck_singleflight(monkeypatch, clean_test_env):
    """
    故障注入 1: Provider 网络异常/超时/崩溃
    - 不能将市场日历标记为 CLOSED (必须保持 UNKNOWN)
    - 严禁卡死 SingleFlight key
    - 当 Provider 恢复后，下一次请求必须能正常执行
    """
    pm, info, path = clean_test_env
    call_count = 0

    class FailingAdapter(BaseDataSource):
        def fetch_daily(self, info, start_date, end_date):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("External Provider Network Timeout!")
            # 第二次调用恢复正常，返回 2035-01-02 对应的真实毫秒时间戳
            from core.time import date_range_to_utc_boundary
            ts_start, _ = date_range_to_utc_boundary("2035-01-02", "2035-01-02", Market.SH)
            bar_ts = ts_start + 15 * 3600 * 1000 - 8 * 3600 * 1000
            return pl.DataFrame({
                "timestamp": [bar_ts],
                "open": [10.0],
                "high": [10.0],
                "low": [10.0],
                "close": [10.0],
                "volume": [100.0],
                "amount": [1000.0],
                "factor": [1.0],
                "nav": [None]
            })

        def fetch_minute(self, *args, **kwargs): return None
        def fetch_snapshot(self, *args, **kwargs): return None
        def fetch_calendar(self, *args, **kwargs): return []
        def fetch_symbols(self, *args, **kwargs): return []

    monkeypatch.setattr(adapter_factory, "get_adapter", lambda m: FailingAdapter())

    test_date = "2035-01-02" # 2035-01-02 为周二，确保初始日历状态为 UNKNOWN

    # 1. 第一次请求：抛出网络异常
    with pytest.raises(RuntimeError, match="Network Timeout"):
        await pm.get_or_fetch(info, KlinePeriod.D1, test_date, test_date)

    # 核心断言：异常不能污染全市场交易日历为 CLOSED！
    calendar_status = meta_db.get_calendar_status("SH", test_date)
    assert calendar_status != "CLOSED", "Provider failure must NOT mark calendar CLOSED!"
    assert calendar_status == "UNKNOWN"

    # 核心断言：SingleFlight key 已安全释放，下一次请求成功重试
    res = await pm.get_or_fetch(info, KlinePeriod.D1, test_date, test_date)
    assert res is not None
    assert len(res) == 1
    assert call_count == 2

@pytest.mark.asyncio
async def test_provider_empty_does_not_mark_calendar_closed(monkeypatch, clean_test_env):
    """
    故障注入 2: Provider 返回 Empty (个股停牌或未交易)
    - 绝不能将全市场交易日历标记为 CLOSED (Provider Empty != Market Closed)
    - 记录标的级无数据记录，杜绝无限重复拉取
    """
    pm, info, path = clean_test_env

    class EmptyAdapter(BaseDataSource):
        def fetch_daily(self, info, start_date, end_date):
            return pl.DataFrame() # 明确返回空数据
        def fetch_minute(self, *args, **kwargs): return None
        def fetch_snapshot(self, *args, **kwargs): return None
        def fetch_calendar(self, *args, **kwargs): return []
        def fetch_symbols(self, *args, **kwargs): return []

    monkeypatch.setattr(adapter_factory, "get_adapter", lambda m: EmptyAdapter())

    res = await pm.get_or_fetch(info, KlinePeriod.D1, "2024-01-03", "2024-01-03")
    assert res is None

    # 全市场日历绝不能被污染为 CLOSED
    assert meta_db.get_calendar_status("SH", "2024-01-03") != "CLOSED"
    # 但该标的已被登记为该日期无数据，防止无限重复拉取
    assert meta_db.is_symbol_no_data(info.symbol, "1d", "2024-01-03") is True

@pytest.mark.asyncio
async def test_parquet_write_failure_preserves_original_and_unlinks_tmp(clean_test_env):
    """
    故障注入 3: Parquet 写入阶段抛出异常 (模拟磁盘满/IO故障)
    - 原文件不受任何损坏
    - 产生的 .tmp 临时文件被安全清理
    """
    pm, info, path = clean_test_env

    # 先准备一个已存在的有效文件
    original_df = pl.DataFrame({
        "timestamp": [1704182400000],
        "open": [10.0], "high": [10.0], "low": [10.0], "close": [10.0],
        "volume": [100.0], "amount": [1000.0], "factor": [1.0], "nav": [None]
    })
    pm.write_parquet(path, original_df)
    original_size = path.stat().st_size

    # 尝试写入新数据，但在 write_parquet 阶段注入异常
    new_df = pl.DataFrame({
        "timestamp": [1704182400000, 1704268800000],
        "open": [10.0, 11.0], "high": [10.0, 11.0], "low": [10.0, 11.0], "close": [10.0, 11.0],
        "volume": [100.0, 200.0], "amount": [1000.0, 2000.0], "factor": [1.0, 1.0], "nav": [None, None]
    })

    with patch.object(pl.DataFrame, "write_parquet", side_effect=IOError("Disk Full Simulation")):
        with pytest.raises(IOError, match="Disk Full Simulation"):
            pm.write_parquet(path, new_df)

    # 断言：原文件保持完好，大小未变
    assert path.exists()
    assert path.stat().st_size == original_size
    read_back = pm.read_parquet(path)
    assert len(read_back) == 1

    # 断言：目录下没有留下未清理的 .tmp 孤儿文件
    tmps = list(path.parent.glob(f"{path.stem}_*.tmp"))
    assert len(tmps) == 0

@pytest.mark.asyncio
async def test_os_replace_failure_preserves_original_and_unlinks_tmp(clean_test_env):
    """
    故障注入 4: os.replace 原子重命名失败 (权限错误/被占用)
    - 原文件保持完好
    - 临时文件被 unlink
    """
    pm, info, path = clean_test_env

    original_df = pl.DataFrame({
        "timestamp": [1704182400000],
        "open": [10.0], "high": [10.0], "low": [10.0], "close": [10.0],
        "volume": [100.0], "amount": [1000.0], "factor": [1.0], "nav": [None]
    })
    pm.write_parquet(path, original_df)

    with patch("os.replace", side_effect=OSError("Permission Denied Simulation")):
        with pytest.raises(OSError, match="Permission Denied Simulation"):
            pm.write_parquet(path, original_df)

    assert path.exists()
    tmps = list(path.parent.glob(f"{path.stem}_*.tmp"))
    assert len(tmps) == 0

def test_reconcile_cleans_corrupt_files_and_orphan_tmps():
    """
    故障注入 5: 磁盘损坏文件与孤儿 .tmp 文件的 Reconcile 自愈
    - 损坏的 Parquet 文件：清理元数据
    - 超过 60 秒的孤儿 .tmp 文件：安全删除
    - 正常文件与元数据不一致：自动修补
    """
    pm = ParquetManager()
    info = SymbolInfo(symbol="CORRUPT.SH.STK", ticker="CORRUPT", market=Market.SH, asset_type=AssetType.STOCK, name="Corrupt Stock", currency="CNY", is_benchmark=False)
    target_p = pm.get_file_path(info, "1d")
    cache_dir = target_p.parent
    cache_dir.mkdir(parents=True, exist_ok=True)

    # 1. 创建损坏的 Parquet 文件
    corrupt_file = cache_dir / "CORRUPT_STK.parquet"
    corrupt_file.write_bytes(b"corrupted_garbage_content")
    meta_db.record_cache_access(
        symbol="CORRUPT.SH.STK",
        period="1d",
        file_path=str(corrupt_file),
        file_size_bytes=100,
        covered_start_date="2024-01-01",
        covered_end_date="2024-01-02",
        min_ts=1700000000000,
        max_ts=1700086400000,
        row_count=2
    )

    # 2. 创建一个超时的孤儿 .tmp 文件 (mtime 设置为 200 秒前)
    orphan_tmp = cache_dir / "ORPHAN_20240101.tmp"
    orphan_tmp.write_bytes(b"temporary data")
    old_time = time.time() - 200
    os.utime(orphan_tmp, (old_time, old_time))

    try:
        report = pm.reconcile_storage_metadata()
        # 断言：孤儿 tmp 被清理
        assert not orphan_tmp.exists()
        assert report["cleaned_tmps"] >= 1

        # 断言：损坏文件的元数据被移除
        assert meta_db.get_cache_info("CORRUPT.SH.STK", "1d") is None
    finally:
        if corrupt_file.exists(): corrupt_file.unlink()
        if orphan_tmp.exists(): orphan_tmp.unlink()
        meta_db.remove_cache_record("CORRUPT.SH.STK", "1d")

@pytest.mark.asyncio
async def test_singleflight_concurrent_cancellation_resilience():
    """
    故障注入 6: SingleFlight 各种取消场景弹性
    1. Leader 被外部 Cancel -> follower 收到 CancelledError，key 彻底清理
    2. Follower 被外部 Cancel -> 不影响 Leader 的正常执行
    """
    sf = SingleFlightLock()
    leader_started = asyncio.Event()
    leader_finish = asyncio.Event()

    async def long_leader_coro():
        leader_started.set()
        await leader_finish.wait()
        return "SUCCESS"

    # 1. 测试 follower cancellation 不打断 leader
    task_leader = asyncio.create_task(sf.do("TEST_KEY_1", long_leader_coro))
    await leader_started.wait()

    # follower 加入
    task_follower = asyncio.create_task(sf.do("TEST_KEY_1", long_leader_coro))
    await asyncio.sleep(0.01)

    # 取消 follower
    task_follower.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task_follower

    # leader 正常完成
    leader_finish.set()
    res = await task_leader
    assert res == "SUCCESS"
    assert "TEST_KEY_1" not in sf._calls

    # 2. 测试 leader cancellation 正确清理 key 并通知 follower
    leader_finish_2 = asyncio.Event()
    leader_started_2 = asyncio.Event()
    async def cancelling_leader():
        leader_started_2.set()
        await leader_finish_2.wait()
        return "DONE"

    task_leader_2 = asyncio.create_task(sf.do("TEST_KEY_2", cancelling_leader))
    await leader_started_2.wait()

    task_follower_2 = asyncio.create_task(sf.do("TEST_KEY_2", cancelling_leader))
    await asyncio.sleep(0.01)

    # 取消 leader
    task_leader_2.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task_leader_2

    # follower 也应该感知到取消
    with pytest.raises(asyncio.CancelledError):
        await task_follower_2

    # key 必须被清理，绝不能死锁
    assert "TEST_KEY_2" not in sf._calls
