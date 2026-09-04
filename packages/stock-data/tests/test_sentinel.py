import pytest
from pathlib import Path
from storage.sentinel import DiskSentinel
from core.database import MetadataDB

def test_sentinel_stats_and_eviction(tmp_path):
    # 模拟环境目录
    cache_dir = tmp_path / "cache_kline"
    daily_dir = cache_dir / "daily"
    daily_dir.mkdir(parents=True, exist_ok=True)
    db_file = tmp_path / "meta.db"

    test_db = MetadataDB(db_path=db_file)
    sentinel = DiskSentinel()

    # 创建一个真实的临时 parquet/bin 文件用于测试大小
    dummy_file = daily_dir / "test_stock.parquet"
    dummy_file.write_bytes(b"0" * (1024 * 1024)) # 1MB

    test_db.record_cache_access(
        symbol="TEST.SH.STK",
        period="1d",
        file_path=str(dummy_file),
        file_size_bytes=1024 * 1024,
        covered_start_date="2024-01-01",
        covered_end_date="2024-01-15",
        min_ts=1700000000000,
        max_ts=1705000000000,
        row_count=100
    )

    size_bytes = sentinel.get_dir_size_bytes(cache_dir)
    assert size_bytes == 1024 * 1024

    stats = sentinel.get_storage_stats()
    assert "cache_size_gb" in stats
    assert "host_free_disk_gb" in stats
    assert "is_safe" in stats

def test_sentinel_delete_failure_preserves_metadata(monkeypatch, tmp_path):
    """验证当 unlink 发生异常时，Sentinel 必须保留 SQLite 元数据，杜绝元数据丢失而文件残留的脏状态"""
    from storage.sentinel import sentinel
    from core.database import meta_db

    test_file = tmp_path / "mock_stock.parquet"
    test_file.write_bytes(b"mock data")

    sym = "FAIL_UNLINK.SH.STK"
    period = "1m"
    meta_db.record_cache_access(
        symbol=sym,
        period=period,
        file_path=str(test_file),
        file_size_bytes=100,
        covered_start_date="2024-01-01",
        covered_end_date="2024-01-02",
        min_ts=1700000000000,
        max_ts=1700086400000,
        row_count=10
    )

    # 模拟 unlink 抛出 PermissionError
    def mock_unlink(self, *args, **kwargs):
        raise PermissionError("Mock file is locked")

    monkeypatch.setattr(Path, "unlink", mock_unlink)

    # 模拟满足触发淘汰条件
    monkeypatch.setattr(sentinel, "get_storage_stats", lambda: {
        "cache_size_gb": 100.0,
        "host_free_disk_gb": 0.1,
        "is_safe": False
    })
    monkeypatch.setattr(meta_db, "get_lru_candidates", lambda limit: [{
        "symbol": sym,
        "period": period,
        "file_path": str(test_file),
        "file_size_bytes": 100
    }])

    sentinel.check_and_evict()

    # 验证元数据没有被错误删除
    rec = meta_db.get_cache_info(sym, period)
    assert rec is not None
    assert rec["symbol"] == sym

    # 清理测试元数据
    meta_db.remove_cache_record(sym, period)

