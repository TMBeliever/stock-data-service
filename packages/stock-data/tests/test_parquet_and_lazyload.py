import pytest
import time
from core.models import SymbolInfo, Market, AssetType, KlinePeriod
from storage.parquet_manager import ParquetManager

@pytest.mark.live
@pytest.mark.asyncio
async def test_lazyload_and_smart_append_real():
    pm = ParquetManager()
    info = SymbolInfo(
        symbol="SPY.US.ETF",
        ticker="SPY",
        market=Market.US,
        asset_type=AssetType.ETF,
        name="SPDR S&P 500 ETF",
        currency="USD",
        is_benchmark=False # 作为测试，放入 Lazy 缓存池
    )
    period = KlinePeriod.D1

    # 1. 首次调用：Cache Miss，从真实源抓取并落地 Parquet
    t0 = time.time()
    df1 = await pm.get_or_fetch(info, period, start_date="2024-01-01", end_date="2024-01-15")
    cost1 = time.time() - t0

    assert df1 is not None
    assert not df1.is_empty()
    path = pm.get_file_path(info, period.value)
    assert path.exists()

    # 2. 二次调用相同区间：Cache Hit，直接读本地 Parquet，耗时显著缩短
    t0 = time.time()
    df2 = await pm.get_or_fetch(info, period, start_date="2024-01-01", end_date="2024-01-15")
    cost2 = time.time() - t0

    assert df2 is not None
    assert len(df1) == len(df2)
    assert cost2 < cost1 # 本地 Parquet 读取比首次外部网络拉取显著更快
    assert cost2 < 0.20

    # 3. 扩展区间调用：触发 Smart Append 增量补齐 (如扩展到 2024-01-31)
    df3 = await pm.get_or_fetch(info, period, start_date="2024-01-01", end_date="2024-01-31")
    assert df3 is not None
    assert len(df3) > len(df2) # 包含了后续日期的真实数据

def test_parquet_atomic_write_failure_preserves_original(monkeypatch, tmp_path):
    """测试当 write_parquet 过程中发生写异常时，原有 Parquet 文件绝不被破坏，且临时文件被清理"""
    import polars as pl
    pm = ParquetManager()
    target_file = tmp_path / "original.parquet"
    
    # 1. 先写入一个合法的原始文件
    df_orig = pl.DataFrame({"a": [1, 2, 3]})
    pm.write_parquet(target_file, df_orig)
    assert target_file.exists()
    assert len(pm.read_parquet(target_file)) == 3

    # 2. 模拟写入临时文件时抛出异常 (如磁盘写满或中断)
    def mock_write_parquet_fail(self, *args, **kwargs):
        raise IOError("Disk write error")

    monkeypatch.setattr(pl.DataFrame, "write_parquet", mock_write_parquet_fail)

    df_corrupted = pl.DataFrame({"a": [999]})
    with pytest.raises(IOError, match="Disk write error"):
        pm.write_parquet(target_file, df_corrupted)

    # 3. 验证原文件毫发无损
    df_checked = pm.read_parquet(target_file)
    assert len(df_checked) == 3
    assert df_checked["a"].to_list() == [1, 2, 3]

    # 4. 验证没有残留临时文件
    tmp_files = list(tmp_path.glob("*.tmp"))
    assert len(tmp_files) == 0

def test_reconcile_storage_metadata(tmp_path):
    """测试存储元数据双向对齐：
    1. 清理物理文件已丢失但 SQLite 仍有缓存记录的孤儿项；
    2. 物理 Parquet 文件存在但 SQLite 缺失记录时，自动解析并恢复元数据。
    """
    import polars as pl
    from core.database import meta_db
    from storage.parquet_manager import ParquetManager

    pm = ParquetManager()
    
    # 场景 1: 构造孤儿元数据记录 (文件物理不存在)
    orphan_sym = "ORPHAN.SH.STK"
    fake_path = tmp_path / "non_existent.parquet"
    meta_db.record_cache_access(
        symbol=orphan_sym,
        period="1d",
        file_path=str(fake_path),
        file_size_bytes=1024,
        covered_start_date="2024-01-01",
        covered_end_date="2024-01-10",
        min_ts=1704067200000,
        max_ts=1704844800000,
        row_count=10
    )
    assert meta_db.get_cache_info(orphan_sym, "1d") is not None

    # 场景 2: 构造物理存在但元数据缺失的未登记文件
    from config import settings
    restored_sym = "600999.SH.STK"
    sh_dir = settings.CACHE_KLINE_DIR / "daily" / "SH"
    sh_dir.mkdir(parents=True, exist_ok=True)
    real_parquet = sh_dir / "600999_STK.parquet"

    df_test = pl.DataFrame({
        "timestamp": [1704067200000, 1704153600000],
        "open": [10.0, 10.5],
        "high": [11.0, 11.2],
        "low": [9.8, 10.1],
        "close": [10.5, 10.8],
        "volume": [1000.0, 1200.0],
        "amount": [10500.0, 12960.0],
        "factor": [1.0, 1.0],
        "nav": [None, None]
    })
    pm.write_parquet(real_parquet, df_test)
    # 确保此时元数据中没有它
    meta_db.remove_cache_record(restored_sym, "1d")
    assert meta_db.get_cache_info(restored_sym, "1d") is None

    # 执行对齐
    res = pm.reconcile_storage_metadata()
    assert res["cleaned_orphans"] >= 1
    assert res["restored_records"] >= 1

    # 验证孤儿已清理
    assert meta_db.get_cache_info(orphan_sym, "1d") is None

    # 验证缺失项已成功恢复元数据
    restored_rec = meta_db.get_cache_info(restored_sym, "1d")
    assert restored_rec is not None
    assert restored_rec["row_count"] == 2
    assert restored_rec["covered_start_date"] == "2024-01-01"

    # 清理测试生成的文件与记录
    if real_parquet.exists():
        real_parquet.unlink()
    meta_db.remove_cache_record(restored_sym, "1d")

@pytest.mark.asyncio
async def test_out_of_range_provider_response_contract(monkeypatch):
    """Test A: 验证当 provider 返回完全在用户请求范围之外的数据时，ParquetManager 严格过滤，绝不把范围外脏数据返回给调用方"""
    from core.models import SymbolInfo, Market, AssetType, KlinePeriod
    from storage.parquet_manager import ParquetManager
    from adapters.factory import adapter_factory
    from adapters.base import BaseDataSource
    import polars as pl

    pm = ParquetManager()
    info = SymbolInfo(
        symbol="OUTOFRANGE.SH.STK",
        ticker="OUTOFRANGE",
        market=Market.SH,
        asset_type=AssetType.STOCK,
        name="OutOfRange Stock",
        currency="CNY",
        is_benchmark=False
    )

    # 模拟外部 Provider 发生异常偏离，返回了 2025 年的数据
    mock_df_2025 = pl.DataFrame({
        "timestamp": [1735689600000, 1735776000000], # 2025-01-01, 2025-01-02
        "open": [10.0, 11.0],
        "high": [12.0, 13.0],
        "low": [9.0, 10.0],
        "close": [11.0, 12.0],
        "volume": [100.0, 200.0],
        "amount": [1100.0, 2400.0],
        "factor": [1.0, 1.0],
        "nav": [None, None]
    })

    class MockAdapter(BaseDataSource):
        def fetch_daily(self, info, start_date, end_date):
            return mock_df_2025
        def fetch_minute(self, info, period, start_date, end_date):
            return mock_df_2025
        def fetch_snapshot(self, market):
            return None
        def fetch_calendar(self, market, year):
            return []
        def fetch_symbols(self, market):
            return []

    monkeypatch.setattr(adapter_factory, "get_adapter", lambda m: MockAdapter())

    # 用户请求 2024-01-01 至 2024-01-05
    res = await pm.get_or_fetch(info, KlinePeriod.D1, "2024-01-01", "2024-01-05")

    # 核心断言：绝不能返回 2025 年的数据！返回必须为 None (或空)
    assert res is None, "Range contract violated! Out-of-range rows were leaked to caller!"

    # 清理测试生成的 parquet 文件
    p = pm.get_file_path(info, "1d")
    if p.exists():
        p.unlink()

@pytest.mark.asyncio
async def test_parquet_cache_gap_detection_and_smart_repair(monkeypatch):
    """
    P1 测试矩阵：
    1. 完整 cache → 不 fetch
    2. 左侧缺口 → fetch
    3. 右侧缺口 → fetch
    4. 内部缺口 → 只 fetch 缺失范围
    5. 周末不被认为是 gap
    6. A 股午休不被认为是 minute gap
    """
    from core.models import SymbolInfo, Market, AssetType, KlinePeriod
    from storage.parquet_manager import ParquetManager
    from adapters.factory import adapter_factory
    from adapters.base import BaseDataSource
    from core.time import date_to_utc_boundary
    from core.database import meta_db
    import datetime
    import polars as pl

    pm = ParquetManager()
    info = SymbolInfo(
        symbol="GAPTEST.SH.STK",
        ticker="GAPTEST",
        market=Market.SH,
        asset_type=AssetType.STOCK,
        name="Gap Test Stock",
        currency="CNY",
        is_benchmark=False
    )
    path_1d = pm.get_file_path(info, "1d")
    path_1m = pm.get_file_path(info, "1m")
    if path_1d.exists(): path_1d.unlink()
    if path_1m.exists(): path_1m.unlink()

    fetch_calls = []

    def make_bar(date_str, close_price=10.0):
        s_ts, _ = date_to_utc_boundary(date_str, Market.SH)
        ts = s_ts + 15 * 3600 * 1000 - 8 * 3600 * 1000
        return {
            "timestamp": ts,
            "open": close_price,
            "high": close_price,
            "low": close_price,
            "close": close_price,
            "volume": 100.0,
            "amount": 1000.0,
            "factor": 1.0,
            "nav": None
        }

    class TrackingAdapter(BaseDataSource):
        def fetch_daily(self, info, start_date, end_date):
            fetch_calls.append(("1d", start_date, end_date))
            cur = datetime.datetime.strptime(start_date, "%Y-%m-%d").date()
            end = datetime.datetime.strptime(end_date, "%Y-%m-%d").date()
            rows = []
            while cur <= end:
                if cur.weekday() not in (5, 6):
                    rows.append(make_bar(cur.strftime("%Y-%m-%d")))
                cur += datetime.timedelta(days=1)
            if not rows:
                return None
            return pl.DataFrame(rows)

        def fetch_minute(self, info, period, start_date, end_date):
            fetch_calls.append(("1m", start_date, end_date))
            return None
        def fetch_snapshot(self, market):
            return None
        def fetch_calendar(self, market, year):
            return []
        def fetch_symbols(self, market):
            return []

    monkeypatch.setattr(adapter_factory, "get_adapter", lambda m: TrackingAdapter())

    try:
        # 4. 准备一个具有内部历史缺口的初始 Parquet: 包含 2024-01-01(周一), 2024-01-02(周二), 2024-01-03(周三), 2024-01-05(周五)
        # 缺口为：2024-01-04 (周四)
        init_rows = [
            make_bar("2024-01-01"),
            make_bar("2024-01-02"),
            make_bar("2024-01-03"),
            make_bar("2024-01-05"),
        ]
        df_init = pl.DataFrame(init_rows).sort("timestamp")
        pm.write_parquet(path_1d, df_init)

        # 记录元数据覆盖范围 2024-01-01 ~ 2024-01-05
        meta_db.record_cache_access(
            symbol=info.symbol,
            period="1d",
            file_path=str(path_1d),
            file_size_bytes=path_1d.stat().st_size,
            covered_start_date="2024-01-01",
            covered_end_date="2024-01-05",
            min_ts=int(df_init["timestamp"].min()),
            max_ts=int(df_init["timestamp"].max()),
            row_count=len(df_init)
        )

        # 4. 触发查询 2024-01-01 ~ 2024-01-05
        fetch_calls.clear()
        res = await pm.get_or_fetch(info, KlinePeriod.D1, "2024-01-01", "2024-01-05")
        assert res is not None
        assert len(res) == 5 # 包含 01, 02, 03, 04, 05

        # 核心断言 4: 只 fetch 内部缺失的 2024-01-04，绝不全量重新拉取 01-01 ~ 01-05！
        assert len(fetch_calls) == 1
        assert fetch_calls[0] == ("1d", "2024-01-04", "2024-01-04")

        # 1. 完整 cache → 不 fetch
        fetch_calls.clear()
        res_cached = await pm.get_or_fetch(info, KlinePeriod.D1, "2024-01-01", "2024-01-05")
        assert res_cached is not None
        assert len(res_cached) == 5
        assert len(fetch_calls) == 0 # 完整缓存命中，0 次 fetch！

        # 2. 左侧缺口 → fetch 2023-12-28 ~ 2024-01-01
        fetch_calls.clear()
        res_left = await pm.get_or_fetch(info, KlinePeriod.D1, "2023-12-28", "2024-01-05")
        assert res_left is not None
        assert any(c[1] == "2023-12-28" for c in fetch_calls)

        # 3. 右侧缺口 → fetch 2024-01-05 ~ 2024-01-10
        fetch_calls.clear()
        res_right = await pm.get_or_fetch(info, KlinePeriod.D1, "2023-12-28", "2024-01-10")
        assert res_right is not None
        assert any(c[2] == "2024-01-10" for c in fetch_calls)

        # 5. 周末不被认为是 gap: 查询 2024-01-05(周五) 到 2024-01-08(周一)
        fetch_calls.clear()
        res_weekend = await pm.get_or_fetch(info, KlinePeriod.D1, "2024-01-05", "2024-01-08")
        assert res_weekend is not None
        assert len(fetch_calls) == 0 # 周末 01-06, 01-07 不被判定为 gap，不触发 fetch！

        # 6. A 股午休不被认为是 minute gap
        # 准备一天完整的 1 分钟线数据 (09:30-11:30, 13:00-15:00)
        s_day, _ = date_to_utc_boundary("2024-01-09", Market.SH)
        # 早盘 09:30 - 11:30 (120 根)
        m_rows = []
        t_base = s_day + 9 * 3600 * 1000 + 30 * 60 * 1000 - 8 * 3600 * 1000
        for i in range(120):
            m_rows.append({"timestamp": t_base + i * 60000, "open": 10.0, "high": 10.0, "low": 10.0, "close": 10.0, "volume": 10.0, "amount": 100.0, "factor": 1.0, "nav": None})
        # 午盘 13:00 - 15:00 (120 根)
        t_base_afternoon = s_day + 13 * 3600 * 1000 - 8 * 3600 * 1000
        for i in range(120):
            m_rows.append({"timestamp": t_base_afternoon + i * 60000, "open": 10.0, "high": 10.0, "low": 10.0, "close": 10.0, "volume": 10.0, "amount": 100.0, "factor": 1.0, "nav": None})

        df_1m = pl.DataFrame(m_rows).sort("timestamp")
        pm.write_parquet(path_1m, df_1m)
        meta_db.record_cache_access(
            symbol=info.symbol,
            period="1m",
            file_path=str(path_1m),
            file_size_bytes=path_1m.stat().st_size,
            covered_start_date="2024-01-09",
            covered_end_date="2024-01-09",
            min_ts=int(df_1m["timestamp"].min()),
            max_ts=int(df_1m["timestamp"].max()),
            row_count=len(df_1m)
        )

        fetch_calls.clear()
        res_1m = await pm.get_or_fetch(info, KlinePeriod.M1, "2024-01-09", "2024-01-09")
        assert res_1m is not None
        assert len(res_1m) == 240
        assert len(fetch_calls) == 0 # 午休 11:30 ~ 13:00 不被误判为 gap，0 次 fetch！

    finally:
        if path_1d.exists(): path_1d.unlink()
        if path_1m.exists(): path_1m.unlink()
        meta_db.remove_cache_record(info.symbol, "1d")
        meta_db.remove_cache_record(info.symbol, "1m")




