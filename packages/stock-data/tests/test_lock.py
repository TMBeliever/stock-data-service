import pytest
import asyncio
from core.lock import SingleFlightLock

@pytest.mark.asyncio
async def test_single_flight_mutual_exclusion():
    lock = SingleFlightLock()
    execution_order = []

    async def worker(worker_id: int, delay: float):
        async with lock.acquire("AAPL.US.STK"):
            execution_order.append(f"start_{worker_id}")
            await asyncio.sleep(delay)
            execution_order.append(f"end_{worker_id}")

    # 并发启动两个争夺同一 key 的 worker
    await asyncio.gather(
        worker(1, 0.05),
        worker(2, 0.01)
    )

    # 验证必须先完成 worker 1，才能进入 worker 2
    assert execution_order == ["start_1", "end_1", "start_2", "end_2"]

@pytest.mark.asyncio
async def test_single_flight_different_keys():
    lock = SingleFlightLock()
    started = []

    async def worker(key: str):
        async with lock.acquire(key):
            started.append(key)
            await asyncio.sleep(0.02)

    # 两个不同 key 可以并发运行
    await asyncio.gather(
        worker("KEY_A"),
        worker("KEY_B")
    )

    assert set(started) == {"KEY_A", "KEY_B"}

@pytest.mark.asyncio
async def test_single_flight_request_coalescing():
    """验证真正的 Request Coalescing：并发 10 个相同请求仅触发 1 次底层抓取"""
    lock = SingleFlightLock()
    call_count = 0

    async def expensive_upstream_fetch():
        nonlocal call_count
        call_count += 1
        await asyncio.sleep(0.05)
        return {"data": "ok", "count": call_count}

    # 并发 10 个请求争夺相同 key
    tasks = [lock.do("AAPL.US.STK", expensive_upstream_fetch) for _ in range(10)]
    results = await asyncio.gather(*tasks)

    # 1. 10 个协程获得完全相同的结果
    for r in results:
        assert r == {"data": "ok", "count": 1}

    # 2. 真实上游执行仅触发了 1 次 (其余 9 次全部共享结果)
    assert call_count == 1

@pytest.mark.asyncio
async def test_single_flight_leader_exception():
    """测试 Leader 抛出异常时，所有等待该 Future 的 Followers 均收到相同异常"""
    lock = SingleFlightLock()
    call_count = 0

    async def failing_fetch():
        nonlocal call_count
        call_count += 1
        await asyncio.sleep(0.02)
        raise RuntimeError("Provider connection reset")

    tasks = [lock.do("FAIL_KEY", failing_fetch) for _ in range(5)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    assert call_count == 1
    assert len(results) == 5
    for err in results:
        assert isinstance(err, RuntimeError)
        assert "Provider connection reset" in str(err)

@pytest.mark.asyncio
async def test_single_flight_follower_cancelled():
    """测试 Follower 取消不会中断 Leader 执行"""
    lock = SingleFlightLock()
    leader_finished = False

    async def long_fetch():
        nonlocal leader_finished
        await asyncio.sleep(0.1)
        leader_finished = True
        return "leader_done"

    # 启动 leader
    leader_task = asyncio.create_task(lock.do("LONG_KEY", long_fetch))
    await asyncio.sleep(0.01)

    # 启动 follower 并迅速取消 follower
    follower_task = asyncio.create_task(lock.do("LONG_KEY", long_fetch))
    await asyncio.sleep(0.01)
    follower_task.cancel()

    try:
        await follower_task
    except asyncio.CancelledError:
        pass

    # 验证 leader 依然正常成功完成
    leader_res = await leader_task
    assert leader_res == "leader_done"
    assert leader_finished is True

