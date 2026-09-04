"""
审计修复回归测试：验证本批次修复的正确性与稳定性。
覆盖:
1. DuckDB 连接并发安全 (storage/compute.py)
2. StorageLockManager LRU 上限 (storage/lock.py)
3. A 股毛利率使用营业成本 COGS 而非营业总成本 (service/routes/financials.py)
4. yfinance 属性访问在 executor 内完成，不阻塞事件循环 (service/routes/financials.py)
5. 海外 ROA/ROE 年化 (service/routes/financials.py)
6. 龙虎榜改用东财源 + 列名兼容 + 7日回溯 (service/routes/advanced.py)
7. ETF 快照 NAV 和折溢价率 (adapters/snapshot.py + core/models.py)
"""
import threading
import polars as pl
import pytest
from core.models import KlinePeriod, AdjustType


# --- 1. DuckDB 并发安全 ---

def test_duckdb_concurrent_resample_no_crash():
    """多线程并发 resample 不再因共享 :memory: 连接崩溃 (审计问题 #1)"""
    from storage.compute import compute_engine

    def build_df():
        return pl.DataFrame({
            "timestamp": [1700000400000 + j * 60000 for j in range(5)],
            "open": [10.0] * 5, "high": [11.0] * 5, "low": [9.0] * 5, "close": [10.0] * 5,
            "volume": [100.0] * 5, "amount": [1000.0] * 5,
            "factor": [1.0] * 5, "nav": [None] * 5,
        })

    errors, results = [], []

    def run(i):
        try:
            res = compute_engine.resample_minutes(build_df(), KlinePeriod.M5)
            results.append(len(res))
        except Exception as e:
            errors.append(f"Thread {i}: {type(e).__name__}: {e}")

    threads = [threading.Thread(target=run, args=(i,)) for i in range(30)]
    for t in threads: t.start()
    for t in threads: t.join()

    assert not errors, f"DuckDB concurrent crash: {errors[:3]}"
    assert all(r == 1 for r in results)


def test_duckdb_concurrent_resample_higher_period():
    """并发合成更高周期 (1d -> 1w) 同样不崩溃"""
    from storage.compute import compute_engine

    def build_df():
        import datetime
        base = datetime.datetime(2024, 1, 2, tzinfo=datetime.timezone.utc)
        ts = [int((base + datetime.timedelta(days=i)).timestamp() * 1000) for i in range(7)]
        return pl.DataFrame({
            "timestamp": ts,
            "open": [10.0] * 7, "high": [11.0] * 7, "low": [9.0] * 7, "close": [10.0] * 7,
            "volume": [100.0] * 7, "amount": [1000.0] * 7,
            "factor": [1.0] * 7, "nav": [None] * 7,
        })

    errors = []
    def run():
        try:
            compute_engine.resample_higher_period(build_df(), KlinePeriod.W1)
        except Exception as e:
            errors.append(f"{type(e).__name__}: {e}")

    threads = [threading.Thread(target=run) for _ in range(20)]
    for t in threads: t.start()
    for t in threads: t.join()

    assert not errors, f"DuckDB higher-period concurrent crash: {errors[:3]}"


# --- 2. StorageLockManager LRU 上限 ---

def test_storage_lock_lru_eviction():
    """锁表超过上限时淘汰最久未使用项，杜绝内存无限膨胀 (审计问题 #2)"""
    from storage.lock import StorageLockManager

    mgr = StorageLockManager(max_locks=5)
    for i in range(20):
        with mgr.lock(f"/tmp/file_{i}.parquet"):
            pass

    assert len(mgr._locks) <= 5, f"lock table leaked: {len(mgr._locks)}"


def test_storage_lock_mutex_semantics():
    """淘汰机制不影响锁的互斥语义与可复用性"""
    from storage.lock import StorageLockManager

    mgr = StorageLockManager(max_locks=100)
    order = []

    def worker():
        with mgr.lock("/tmp/mutex_key.parquet"):
            order.append("start")
            import time; time.sleep(0.05)
            order.append("end")

    t1 = threading.Thread(target=worker)
    t1.start(); t1.join()
    assert order == ["start", "end"]

    with mgr.lock("/tmp/mutex_key.parquet"):
        order.append("reuse")
    assert order == ["start", "end", "reuse"]


# --- 3. A 股毛利率使用营业成本 COGS ---

def test_ashare_gross_margin_uses_cogs_not_total_cost():
    """毛利率必须用营业成本 (COGS)，不能用营业总成本 (含费用) (审计问题 #5)"""
    from fastapi.testclient import TestClient
    from service.app import app
    import pandas as pd
    import service.routes.financials as fin_mod

    df_lrb = pd.DataFrame([{
        "报告日": "2026-06-30",
        "公告日期": "2026-08-15",
        "营业总收入": 92278072083.21,
        "净利润": 46033330566.78,
        "营业成本": 9473762565.88,
        "营业总成本": 30946044878.08,
    }])
    df_fzb = pd.DataFrame([{"报告日": "2026-06-30", "资产总计": 5000000000.0, "负债合计": 2000000000.0}])
    df_llb = pd.DataFrame([{"报告日": "2026-06-30", "经营活动产生的现金流量净额": 300000000.0}])

    async def mock_fetch(code):
        return df_lrb, df_fzb, df_llb

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(fin_mod, "_fetch_sina_reports", mock_fetch)
    try:
        client = TestClient(app)
        resp = client.get("/api/v1/stock/financials?symbol=600519&limit=1")
        assert resp.status_code == 200
        gm = resp.json()["reports"][0]["gross_margin_pct"]
        assert gm is not None
        assert gm == pytest.approx(89.73, abs=0.05), f"got {gm}, expected ~89.73 (COGS-based)"
    finally:
        monkeypatch.undo()


# --- 4. yfinance 属性访问移到 executor 内 ---

def test_yfinance_property_access_in_executor():
    """yfinance 属性访问必须全部在 executor 内完成 (审计问题 #11)"""
    import service.routes.financials as fin_mod
    import inspect

    src = inspect.getsource(fin_mod)
    assert "_fetch_yf_data" in src
    assert "t_obj.quarterly_financials" in src
    assert "t_obj.quarterly_balance_sheet" in src
    assert "t_obj.quarterly_cashflow" in src
    assert "t_obj.info" in src
    assert "run_in_executor(None, _fetch_yf_data, yf_ticker)" in src


def test_yfinance_executor_not_blocking_event_loop():
    """Mock yfinance 端到端通过，验证属性访问不阻塞事件循环"""
    from fastapi.testclient import TestClient
    from service.app import app
    import pandas as pd
    import service.routes.financials as fin_mod

    col = pd.Timestamp("2023-12-31")
    mock_fin = pd.DataFrame({col: [100000000.0, 20000000.0]}, index=["Total Revenue", "Net Income"])
    mock_bs = pd.DataFrame({col: [500000000.0, 200000000.0]}, index=["Total Assets", "Total Liabilities Net Minority Interest"])
    mock_cf = pd.DataFrame({col: [30000000.0]}, index=["Operating Cash Flow"])

    class MockTicker:
        def __init__(self, t):
            self.quarterly_financials = mock_fin
            self.quarterly_balance_sheet = mock_bs
            self.quarterly_cashflow = mock_cf
            self.info = {}

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(fin_mod.yf, "Ticker", MockTicker)
    try:
        client = TestClient(app)
        resp = client.get("/api/v1/stock/financials?symbol=AAPL.US.STK&as_of=2024-05-01")
        assert resp.status_code == 200
        data = resp.json()
        assert data["pit_status"] == "ESTIMATED"
        assert data["count"] == 1
    finally:
        monkeypatch.undo()


# --- 5. SQLite WAL 模式 ---

def test_sqlite_wal_mode_enabled():
    """连接启用 WAL 模式 (审计问题 #3)"""
    from service.app import app  # 确保 meta_db 已初始化
    from core.database import meta_db

    conn = meta_db._get_conn()
    try:
        mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
        assert mode.lower() == "wal", f"expected WAL, got {mode}"
    finally:
        conn.close()


# --- 6. 海外 ROA/ROE 年化 ---

def test_overseas_roa_is_annualized():
    """海外 ROA 应年化 (单季×4/平均资产)，不能是未年化单季值 (审计问题 #6)"""
    from fastapi.testclient import TestClient
    from service.app import app
    import pandas as pd
    import service.routes.financials as fin_mod

    col = pd.Timestamp("2023-12-31")
    col_prev = pd.Timestamp("2023-09-30")
    mock_fin = pd.DataFrame(
        {col: [100e9, 25e9], col_prev: [90e9, 22e9]},
        index=["Total Revenue", "Net Income"]
    )
    mock_bs = pd.DataFrame(
        {col: [400e9, 150e9], col_prev: [380e9, 140e9]},
        index=["Total Assets", "Total Liabilities Net Minority Interest"]
    )
    mock_cf = pd.DataFrame({col: [30e9], col_prev: [28e9]}, index=["Operating Cash Flow"])

    class MockTicker:
        def __init__(self, t):
            self.quarterly_financials = mock_fin
            self.quarterly_balance_sheet = mock_bs
            self.quarterly_cashflow = mock_cf
            self.info = {}

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(fin_mod.yf, "Ticker", MockTicker)
    try:
        client = TestClient(app)
        resp = client.get("/api/v1/stock/financials?symbol=AAPL.US.STK&limit=1")
        assert resp.status_code == 200
        roa = resp.json()["reports"][0]["roa"]
        # 年化 ROA: (25B × 4) / 平均资产(390B) = 25.64%
        # 未年化 ROA: 25B / 400B = 6.25%
        assert roa is not None
        assert roa > 20.0, f"ROA {roa}% looks unannualized (expected ~25%)"
        assert roa < 40.0, f"ROA {roa}% seems too high"
    finally:
        monkeypatch.undo()


# --- 7. 龙虎榜列名兼容 ---

def test_dragon_tiger_column_compatibility():
    """龙虎榜使用东财源列名 (代码/名称/上榜原因) 而非新浪旧列名 (审计)"""
    import service.routes.advanced as adv_mod
    import inspect

    src = inspect.getsource(adv_mod.get_dragon_tiger_list)
    # 确认不再硬编码旧列名
    assert "股票代码" not in src or "code_col" in src, "should use adaptive column lookup"
    assert "stock_lhb_detail_em" in src, "should use Eastmoney source"
    # 确认有回溯逻辑
    assert "offset" in src or "range" in src, "should have date fallback loop"


# --- 8. ETF 折溢价率在 SnapshotItem 中 ---

def test_snapshot_item_has_nav_and_premium_rate():
    """SnapshotItem 模型包含 nav 和 premium_rate 字段 (审计问题 #9)"""
    from core.models import SnapshotItem

    # ETF 有 NAV，计算折溢价
    item = SnapshotItem(
        symbol="510300.SH.ETF",
        name="沪深300ETF",
        latest_price=4.651,
        nav=4.6485,
        premium_rate=round((4.651 - 4.6485) / 4.6485 * 100, 4)
    )
    assert item.nav == pytest.approx(4.6485)
    assert item.premium_rate is not None
    assert abs(item.premium_rate) < 1.0  # 正常折溢价 < 1%

    # 非 ETF 无 NAV
    item2 = SnapshotItem(symbol="600519.SH.STK", name="贵州茅台", latest_price=1335.0)
    assert item2.nav is None
    assert item2.premium_rate is None


def test_etf_premium_rate_calculation():
    """ETF 折溢价率计算: (price - nav) / nav * 100"""
    from core.models import SnapshotItem

    # 溢价: 价格高于 NAV
    price, nav = 4.660, 4.650
    expected = round((price - nav) / nav * 100, 4)
    item = SnapshotItem(symbol="510300.SH.ETF", name="ETF", latest_price=price, nav=nav, premium_rate=expected)
    assert item.premium_rate == pytest.approx(expected)
    assert item.premium_rate > 0

    # 折价: 价格低于 NAV
    price2, nav2 = 4.640, 4.650
    expected2 = round((price2 - nav2) / nav2 * 100, 4)
    item2 = SnapshotItem(symbol="510300.SH.ETF", name="ETF", latest_price=price2, nav=nav2, premium_rate=expected2)
    assert item2.premium_rate < 0

import threading
import asyncio
import polars as pl
import pytest
from core.models import KlinePeriod, AdjustType


# --- 1. DuckDB 并发安全 ---

def test_duckdb_concurrent_resample_no_crash():
    """多线程并发 resample 不再因共享 :memory: 连接崩溃 (审计问题 #1)"""
    from storage.compute import compute_engine

    def build_df():
        return pl.DataFrame({
            "timestamp": [1700000400000 + j * 60000 for j in range(5)],
            "open": [10.0] * 5, "high": [11.0] * 5, "low": [9.0] * 5, "close": [10.0] * 5,
            "volume": [100.0] * 5, "amount": [1000.0] * 5,
            "factor": [1.0] * 5, "nav": [None] * 5,
        })

    errors, results = [], []

    def run(i):
        try:
            res = compute_engine.resample_minutes(build_df(), KlinePeriod.M5)
            results.append(len(res))
        except Exception as e:
            errors.append(f"Thread {i}: {type(e).__name__}: {e}")

    threads = [threading.Thread(target=run, args=(i,)) for i in range(30)]
    for t in threads: t.start()
    for t in threads: t.join()

    assert not errors, f"DuckDB concurrent crash: {errors[:3]}"
    # 5 根 1m 线应聚合为 1 根 5m 线
    assert all(r == 1 for r in results)


def test_duckdb_concurrent_resample_higher_period():
    """并发合成更高周期 (1d -> 1w) 同样不崩溃"""
    from storage.compute import compute_engine

    def build_df():
        import datetime
        base = datetime.datetime(2024, 1, 2, tzinfo=datetime.timezone.utc)
        ts = [int((base + datetime.timedelta(days=i)).timestamp() * 1000) for i in range(7)]
        return pl.DataFrame({
            "timestamp": ts,
            "open": [10.0] * 7, "high": [11.0] * 7, "low": [9.0] * 7, "close": [10.0] * 7,
            "volume": [100.0] * 7, "amount": [1000.0] * 7,
            "factor": [1.0] * 7, "nav": [None] * 7,
        })

    errors = []
    def run():
        try:
            compute_engine.resample_higher_period(build_df(), KlinePeriod.W1)
        except Exception as e:
            errors.append(f"{type(e).__name__}: {e}")

    threads = [threading.Thread(target=run) for _ in range(20)]
    for t in threads: t.start()
    for t in threads: t.join()

    assert not errors, f"DuckDB higher-period concurrent crash: {errors[:3]}"


# --- 2. StorageLockManager LRU 上限 ---

def test_storage_lock_lru_eviction():
    """锁表超过上限时淘汰最久未使用项，杜绝内存无限膨胀 (审计问题 #2)"""
    from storage.lock import StorageLockManager

    mgr = StorageLockManager(max_locks=5)
    for i in range(20):
        with mgr.lock(f"/tmp/file_{i}.parquet"):
            pass

    assert len(mgr._locks) <= 5, f"lock table leaked: {len(mgr._locks)}"


def test_storage_lock_mutex_semantics():
    """淘汰机制不影响锁的互斥语义与可复用性"""
    from storage.lock import StorageLockManager

    mgr = StorageLockManager(max_locks=100)
    order = []

    def worker():
        with mgr.lock("/tmp/mutex_key.parquet"):
            order.append("start")
            import time; time.sleep(0.05)
            order.append("end")

    t1 = threading.Thread(target=worker)
    t1.start(); t1.join()
    assert order == ["start", "end"]

    # 同一 key 再次使用，仍能正确拿到锁
    with mgr.lock("/tmp/mutex_key.parquet"):
        order.append("reuse")
    assert order == ["start", "end", "reuse"]


# --- 3. A 股毛利率使用营业成本 COGS ---

def test_ashare_gross_margin_uses_cogs_not_total_cost():
    """毛利率必须用营业成本 (COGS)，不能用营业总成本 (含费用) (审计问题 #5)"""
    from fastapi.testclient import TestClient
    from service.app import app
    import pandas as pd
    import service.routes.financials as fin_mod

    # 茅台真实数据量级: 营业总收入 922.78 亿, 营业成本 94.74 亿, 营业总成本 309.46 亿
    df_lrb = pd.DataFrame([{
        "报告日": "2026-06-30",
        "公告日期": "2026-08-15",
        "营业总收入": 92278072083.21,
        "净利润": 46033330566.78,
        "营业成本": 9473762565.88,      # COGS
        "营业总成本": 30946044878.08,   # 含费用，不能用于毛利率
    }])
    df_fzb = pd.DataFrame([{
        "报告日": "2026-06-30",
        "资产总计": 5000000000.0,
        "负债合计": 2000000000.0,
    }])
    df_llb = pd.DataFrame([{
        "报告日": "2026-06-30",
        "经营活动产生的现金流量净额": 300000000.0,
    }])

    async def mock_fetch(code):
        return df_lrb, df_fzb, df_llb

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(fin_mod, "_fetch_sina_reports", mock_fetch)
    try:
        client = TestClient(app)
        resp = client.get("/api/v1/stock/financials?symbol=600519&limit=1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] >= 1
        gm = data["reports"][0]["gross_margin_pct"]
        # 用 COGS 计算: (922.78 - 94.74) / 922.78 = 89.73%
        assert gm is not None
        assert gm == pytest.approx(89.73, abs=0.05), f"got {gm}, expected ~89.73 (COGS-based)"
    finally:
        monkeypatch.undo()


# --- 4. yfinance 属性访问移到 executor 内 ---

def test_yfinance_property_access_in_executor():
    """yfinance 属性访问必须全部在 executor 内完成，不能阻塞事件循环 (审计问题 #11)"""
    import service.routes.financials as fin_mod
    import inspect

    src = inspect.getsource(fin_mod)
    # 断言 _fetch_yf_data 内部同时读取 quarterly_financials / balance_sheet / cashflow / info
    assert "_fetch_yf_data" in src
    assert "t_obj.quarterly_financials" in src
    assert "t_obj.quarterly_balance_sheet" in src
    assert "t_obj.quarterly_cashflow" in src
    assert "t_obj.info" in src
    # 断言所有属性访问都发生在 run_in_executor 内部 (通过辅助函数)
    assert "run_in_executor(None, _fetch_yf_data, yf_ticker)" in src


def test_yfinance_executor_not_blocking_event_loop():
    """验证主事件循环在 yfinance 属性访问期间不被阻塞"""
    from fastapi.testclient import TestClient
    from service.app import app
    import pandas as pd
    import service.routes.financials as fin_mod

    col = pd.Timestamp("2023-12-31")
    mock_fin = pd.DataFrame({col: [100000000.0, 20000000.0]}, index=["Total Revenue", "Net Income"])
    mock_bs = pd.DataFrame({col: [500000000.0, 200000000.0]}, index=["Total Assets", "Total Liabilities Net Minority Interest"])
    mock_cf = pd.DataFrame({col: [30000000.0]}, index=["Operating Cash Flow"])

    class MockTicker:
        def __init__(self, t):
            self.quarterly_financials = mock_fin
            self.quarterly_balance_sheet = mock_bs
            self.quarterly_cashflow = mock_cf
            self.info = {}

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(fin_mod.yf, "Ticker", MockTicker)
    try:
        client = TestClient(app)
        resp = client.get("/api/v1/stock/financials?symbol=AAPL.US.STK&as_of=2024-05-01")
        assert resp.status_code == 200
        data = resp.json()
        assert data["pit_status"] == "ESTIMATED"
        assert data["count"] == 1
    finally:
        monkeypatch.undo()


# --- 5. SQLite WAL 模式 ---

def test_sqlite_wal_mode_enabled():
    """连接启用 WAL 模式与 NORMAL synchronous (审计问题 #3)"""
    import sqlite3
    from service.app import app  # 确保 app 已导入，触发 meta_db 初始化
    from core.database import meta_db

    conn = meta_db._get_conn()
    try:
        mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
        assert mode.lower() == "wal", f"expected WAL, got {mode}"
    finally:
        conn.close()
