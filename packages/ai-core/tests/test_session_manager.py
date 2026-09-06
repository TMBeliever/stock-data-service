import asyncio
import time
import pytest
from ai_core.session_manager import SessionWorker, SessionWorkerManager
from ai_core.config import ai_config

@pytest.mark.asyncio
async def test_session_worker_lifecycle():
    """测试单个 SessionWorker 的初始化、touch 与 UUID 确定性"""
    worker = SessionWorker("test_session_123")
    assert worker.session_id == "test_session_123"
    assert worker.conversation_uuid is not None
    assert len(worker.conversation_uuid) == 36

    # 确定性验证：相同的 session_id 映射到相同的 UUID
    worker2 = SessionWorker("test_session_123")
    assert worker.conversation_uuid == worker2.conversation_uuid

    # touch 验证
    old_time = worker.last_active_at
    await asyncio.sleep(0.01)
    worker.touch()
    assert worker.last_active_at > old_time

@pytest.mark.asyncio
async def test_session_manager_get_and_reuse():
    """测试 SessionWorkerManager 获取与会话复用"""
    manager = SessionWorkerManager()

    w1 = await manager.get_or_create_worker("sess_a")
    w2 = await manager.get_or_create_worker("sess_a")
    w3 = await manager.get_or_create_worker("sess_b")

    # 相同 session_id 获取到同一实例
    assert w1 is w2
    # 不同 session_id 获取到不同实例
    assert w1 is not w3
    assert w1.conversation_uuid != w3.conversation_uuid

    await manager.shutdown_all()
    assert len(manager._workers) == 0

@pytest.mark.asyncio
async def test_session_manager_lru_eviction(monkeypatch):
    """测试当活跃会话超过 CLI_MAX_ACTIVE_SESSIONS 时执行 LRU 淘汰"""
    monkeypatch.setattr(ai_config, "CLI_MAX_ACTIVE_SESSIONS", 3)
    manager = SessionWorkerManager()

    w1 = await manager.get_or_create_worker("sess_1")
    await asyncio.sleep(0.01)
    w2 = await manager.get_or_create_worker("sess_2")
    await asyncio.sleep(0.01)
    w3 = await manager.get_or_create_worker("sess_3")

    assert len(manager._workers) == 3
    assert "sess_1" in manager._workers

    # 再次使用 sess_1 刷新活跃时间
    w1.touch()

    # 新增第四个会话，应淘汰当前最久未活跃的 sess_2
    w4 = await manager.get_or_create_worker("sess_4")
    assert len(manager._workers) == 3
    assert "sess_2" not in manager._workers
    assert "sess_1" in manager._workers
    assert "sess_3" in manager._workers
    assert "sess_4" in manager._workers

    await manager.shutdown_all()

@pytest.mark.asyncio
async def test_session_manager_ttl_sweeping(monkeypatch):
    """测试闲置会话超时 5 分钟 (模拟缩短为 0.1 秒) 后自动 sweep 回收释放"""
    monkeypatch.setattr(ai_config, "CLI_SESSION_TTL", 0.05)
    manager = SessionWorkerManager()

    w1 = await manager.get_or_create_worker("sess_temp")
    assert "sess_temp" in manager._workers

    # 等待超过 TTL
    await asyncio.sleep(0.07)
    await manager.sweep_expired_workers()

    assert "sess_temp" not in manager._workers
    await manager.shutdown_all()
