import pytest
from pathlib import Path
from core.database import MetadataDB
from core.models import SymbolInfo, Market, AssetType

@pytest.fixture
def test_db(tmp_path):
    db_file = tmp_path / "test_meta.db"
    return MetadataDB(db_path=db_file)

def test_symbol_upsert_and_query(test_db):
    sym = SymbolInfo(
        symbol="600519.SH.STK",
        ticker="600519",
        market=Market.SH,
        asset_type=AssetType.STOCK,
        name="贵州茅台",
        currency="CNY",
        is_benchmark=False
    )
    test_db.upsert_symbol(sym)

    record = test_db.get_symbol("600519.SH.STK")
    assert record is not None
    assert record["name"] == "贵州茅台"
    assert record["ticker"] == "600519"
    assert record["market"] == "SH"

    # 测试列表过滤
    items = test_db.list_symbols(market="SH", asset_type="STK")
    assert len(items) == 1
    assert items[0]["symbol"] == "600519.SH.STK"

def test_trading_calendar(test_db):
    test_db.set_calendar_date(market="US", trade_date="2026-07-04", is_open=False) # 独立日休市
    test_db.set_calendar_date(market="US", trade_date="2026-07-06", is_open=True)

    assert test_db.is_trading_day("US", "2026-07-04") is False
    assert test_db.is_trading_day("US", "2026-07-06") is True

    # 未登记但为周末 (2026-07-05 为周日) -> 判定为 False (非交易日)
    assert test_db.is_trading_day("US", "2026-07-05") is False
    assert test_db.get_calendar_status("US", "2026-07-05") == "CLOSED"

    # 未登记的工作日 (2099-01-01 周四) -> 严禁默认为 True，必须返回 None (UNKNOWN)
    assert test_db.is_trading_day("US", "2099-01-01") is None
    assert test_db.get_calendar_status("US", "2099-01-01") == "UNKNOWN"

def test_cache_access_and_lru(test_db):
    test_db.record_cache_access(
        symbol="AAPL.US.STK",
        period="1d",
        file_path="/fake/aapl.parquet",
        file_size_bytes=1024 * 1024,
        covered_start_date="2024-01-01",
        covered_end_date="2024-01-15",
        min_ts=1700000000000,
        max_ts=1705000000000,
        row_count=250
    )

    info = test_db.get_cache_info("AAPL.US.STK", "1d")
    assert info is not None
    assert info["file_size_bytes"] == 1024 * 1024
    assert info["hit_count"] == 1

    # 再次 touch
    test_db.touch_cache("AAPL.US.STK", "1d")
    info2 = test_db.get_cache_info("AAPL.US.STK", "1d")
    assert info2["hit_count"] == 2

    # LRU 候选
    candidates = test_db.get_lru_candidates(limit=10)
    assert len(candidates) == 1
    assert candidates[0]["symbol"] == "AAPL.US.STK"

    # 删除
    test_db.remove_cache_record("AAPL.US.STK", "1d")
    assert test_db.get_cache_info("AAPL.US.STK", "1d") is None

def test_calendar_lifecycle_and_symbol_no_data(test_db):
    """
    P1 审计：验证 Calendar 状态转换生命周期与标的级空数据隔离：
    1. UNKNOWN -> OPEN 成功
    2. OPEN -> CLOSED 被防降级安全逻辑拦截 (除非 force=True)
    3. 标的级空数据记录与全局日历解耦
    """
    # 1. UNKNOWN -> OPEN
    assert test_db.get_calendar_status("SH", "2024-01-08") == "UNKNOWN"
    test_db.set_calendar_date("SH", "2024-01-08", is_open=True)
    assert test_db.get_calendar_status("SH", "2024-01-08") == "OPEN"

    # 2. OPEN -> CLOSED: 严禁因普通未授权调用被篡改为 CLOSED
    test_db.set_calendar_date("SH", "2024-01-08", is_open=False, force=False)
    assert test_db.get_calendar_status("SH", "2024-01-08") == "OPEN" # 仍然保持 OPEN！

    # 仅当 force=True 时允许官方覆写
    test_db.set_calendar_date("SH", "2024-01-08", is_open=False, force=True)
    assert test_db.get_calendar_status("SH", "2024-01-08") == "CLOSED"

    # 3. 标的级空数据隔离 (个股停牌不影响全市场日历)
    assert test_db.is_symbol_no_data("000001.SZ.STK", "1d", "2024-01-09") is False
    test_db.mark_symbol_no_data("000001.SZ.STK", "1d", "2024-01-09")
    assert test_db.is_symbol_no_data("000001.SZ.STK", "1d", "2024-01-09") is True
    # 不影响其他标的
    assert test_db.is_symbol_no_data("600519.SH.STK", "1d", "2024-01-09") is False

    # 清除
    test_db.clear_symbol_no_data("000001.SZ.STK", "1d")
    assert test_db.is_symbol_no_data("000001.SZ.STK", "1d", "2024-01-09") is False

def test_database_schema_migration_from_legacy_db(tmp_path):
    """
    P2-1 审计：验证从旧版本数据库 (无 updated_at 字段) 启动时：
    - 自动触发 schema migration 补充 updated_at 字段
    - 旧历史记录完好保留且能够正常进行 TTL 有效性校验
    """
    import sqlite3
    legacy_db_file = tmp_path / "legacy_meta.db"
    conn = sqlite3.connect(legacy_db_file)
    # 创建旧版本表结构 (只有 created_at，缺少 updated_at)
    conn.execute("""
    CREATE TABLE symbol_no_data_records (
        symbol TEXT NOT NULL,
        period TEXT NOT NULL,
        trade_date TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (symbol, period, trade_date)
    );
    """)
    conn.execute("INSERT INTO symbol_no_data_records (symbol, period, trade_date) VALUES ('LEGACY.SH.STK', '1d', '2024-01-02');")
    conn.commit()
    conn.close()

    # 初始化 MetadataDB，自动触发 init_db() 中的 schema migration
    upgraded_db = MetadataDB(db_path=legacy_db_file)
    assert upgraded_db.is_symbol_no_data("LEGACY.SH.STK", "1d", "2024-01-02") is True

    # 验证字段已被成功添加
    with upgraded_db._get_conn() as c:
        cols = [col[1] for col in c.execute("PRAGMA table_info(symbol_no_data_records)").fetchall()]
        assert "updated_at" in cols
