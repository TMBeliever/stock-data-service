import pytest
import service.scheduler
from service.scheduler import scheduler

def test_scheduler_imports():
    """验证 scheduler 模块及其类型标注导入正常无 NameError"""
    assert hasattr(service.scheduler, "DailyScheduler")
    assert hasattr(service.scheduler, "scheduler")
    assert service.scheduler.DailyScheduler is not None


@pytest.mark.asyncio
async def test_scheduler_get_watchlist():
    """测试调度器自选股池识别"""
    watchlist = scheduler.get_watchlist()
    assert len(watchlist) > 0
    symbols = [w.symbol for w in watchlist]
    assert "000300.SH.IDX" in symbols
    assert "SPX.US.IDX" in symbols

@pytest.mark.asyncio
async def test_scheduler_sync_watchlist_real():
    """测试真实盘后增量补齐与安全巡检"""
    res = await scheduler.sync_watchlist()
    assert "sync_date" in res
    assert res["total_watchlist"] > 0
    assert res["success"] >= 1
    assert res["storage_status"]["is_safe"] is True
