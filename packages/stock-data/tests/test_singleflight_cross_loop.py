import pytest
import asyncio
import threading
import time
import concurrent.futures

from core.lock import SingleFlightLock

def run_in_thread_event_loop(coro_fn):
    """在一个独立的系统线程及其独立的 asyncio event loop 中执行协程"""
    result = None
    error = None

    def worker():
        nonlocal result, error
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(coro_fn())
        except Exception as e:
            error = e
        finally:
            loop.close()

    t = threading.Thread(target=worker)
    t.start()
    t.join()
    if error:
        raise error
    return result

def test_singleflight_cross_threads_and_event_loops():
    """
    P0 审计：验证 SingleFlight 跨多个独立线程与独立 Event Loop 并发调用
    - 绝对不能报 'Task got Future attached to a different loop'
    - 绝对不能报 'Lock is bound to a different event loop'
    - 所有并发线程共享且仅发起一次 leader 执行
    """
    sf = SingleFlightLock()
    call_count = 0
    leader_started = threading.Event()
    leader_continue = threading.Event()

    async def leader_task():
        nonlocal call_count
        call_count += 1
        leader_started.set()
        # 模拟外部 IO 等待，确保 follower 有机会加入
        while not leader_continue.is_set():
            await asyncio.sleep(0.01)
        return "CROSS_LOOP_SUCCESS"

    results = {}
    errors = {}

    def thread_worker(thread_id: int):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            async def run():
                return await sf.do("CROSS_KEY", leader_task)
            results[thread_id] = loop.run_until_complete(run())
        except Exception as e:
            errors[thread_id] = e
        finally:
            loop.close()

    # 启动 5 个独立线程，每个线程有自己独立的 event loop
    threads = []
    for i in range(5):
        t = threading.Thread(target=thread_worker, args=(i,))
        threads.append(t)

    # 启动第一个线程 (leader)
    threads[0].start()
    leader_started.wait(timeout=2.0)

    # 启动其余 4 个线程 (followers)
    for t in threads[1:]:
        t.start()

    time.sleep(0.05) # 让 followers 成功登记并加入等待
    leader_continue.set() # 唤醒 leader 完成计算

    for t in threads:
        t.join(timeout=3.0)

    # 核心断言：
    # 1. 没有抛出任何跨 loop 的 RuntimeError
    assert len(errors) == 0, f"Cross-loop errors occurred: {errors}"
    # 2. 所有 5 个线程成功拿到相同结果
    assert len(results) == 5
    for i in range(5):
        assert results[i] == "CROSS_LOOP_SUCCESS"
    # 3. 真实计算仅执行了 1 次 (Request Coalescing 完美生效)
    assert call_count == 1

def test_singleflight_leader_exception_cross_loops():
    """
    P0 审计：Leader 抛出异常时，所有跨 loop 的 Followers 均能安全感知并接收该异常，绝不死锁
    """
    sf = SingleFlightLock()
    leader_started = threading.Event()

    async def failing_task():
        leader_started.set()
        await asyncio.sleep(0.05)
        raise ValueError("Simulated Leader Failure")

    errors = {}

    def thread_worker(thread_id: int):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            async def run():
                return await sf.do("FAIL_KEY", failing_task)
            loop.run_until_complete(run())
        except Exception as e:
            errors[thread_id] = e
        finally:
            loop.close()

    t1 = threading.Thread(target=thread_worker, args=(1,))
    t2 = threading.Thread(target=thread_worker, args=(2,))
    t1.start()
    leader_started.wait(timeout=2.0)
    t2.start()

    t1.join(timeout=2.0)
    t2.join(timeout=2.0)

    assert 1 in errors and isinstance(errors[1], ValueError)
    assert 2 in errors and isinstance(errors[2], ValueError)
    assert "FAIL_KEY" not in sf._calls

def test_singleflight_acquire_mutual_exclusion_cross_loops():
    """
    P0 审计：验证 acquire(key) 在不同线程与不同 event loop 之间的非阻塞互斥排他性
    """
    sf = SingleFlightLock()
    execution_order = []
    lock_released = threading.Event()

    def worker_1():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        async def task():
            async with sf.acquire("MUTEX_KEY"):
                execution_order.append("worker_1_entered")
                while not lock_released.is_set():
                    await asyncio.sleep(0.01)
                execution_order.append("worker_1_exited")
        loop.run_until_complete(task())
        loop.close()

    def worker_2():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        async def task():
            # worker_2 会在 worker_1 持有锁期间等待
            async with sf.acquire("MUTEX_KEY"):
                execution_order.append("worker_2_entered")
        loop.run_until_complete(task())
        loop.close()

    t1 = threading.Thread(target=worker_1)
    t2 = threading.Thread(target=worker_2)

    t1.start()
    time.sleep(0.05)
    t2.start()
    time.sleep(0.05)

    # 此时 worker_1 必须已经进入，而 worker_2 必须仍在等待
    assert execution_order == ["worker_1_entered"]

    # 释放锁
    lock_released.set()
    t1.join(timeout=2.0)
    t2.join(timeout=2.0)

    # 严格互斥顺序
    assert execution_order == ["worker_1_entered", "worker_1_exited", "worker_2_entered"]

def test_singleflight_cancelled_waiter_does_not_block_next():
    """
    P0-1 & P0-2 核心回归测试：
    Leader A 运行中，Waiter B, C, D 依次入队排队等待。
    随后 Waiter B 被外部 Cancel。
    当 Leader A 完成并 release 时：
    - Waiter B 必须被跳过，抛出 CancelledError
    - Waiter C 必须被唤醒并成功获得锁执行
    - Waiter D 接着被唤醒并成功获得锁执行
    - 绝无死锁或后续 Waiter 永久等待！
    """
    sf = SingleFlightLock()
    a_started = threading.Event()
    a_continue = threading.Event()
    events_log = []

    async def leader_a():
        async with sf.acquire("CANCEL_MUTEX_KEY"):
            events_log.append("A_ENTERED")
            a_started.set()
            while not a_continue.is_set():
                await asyncio.sleep(0.01)
            events_log.append("A_EXITED")

    async def waiter(name: str):
        try:
            async with sf.acquire("CANCEL_MUTEX_KEY"):
                events_log.append(f"{name}_ENTERED")
                await asyncio.sleep(0.01)
                events_log.append(f"{name}_EXITED")
        except asyncio.CancelledError:
            events_log.append(f"{name}_CANCELLED")
            raise

    async def main_coro():
        task_a = asyncio.create_task(leader_a())
        await asyncio.sleep(0.01)

        task_b = asyncio.create_task(waiter("B"))
        task_c = asyncio.create_task(waiter("C"))
        task_d = asyncio.create_task(waiter("D"))
        await asyncio.sleep(0.02)

        # 取消 Waiter B
        task_b.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task_b

        # 唤醒 Leader A 完成
        a_continue.set()
        await task_a

        # 等待 C 和 D 顺利执行完成
        await task_c
        await task_d

    run_in_thread_event_loop(main_coro)

    # 核心断言：B 被成功取消，而 C 与 D 依次顺利执行，绝无卡死！
    assert "A_ENTERED" in events_log
    assert "B_CANCELLED" in events_log
    assert "C_ENTERED" in events_log
    assert "C_EXITED" in events_log
    assert "D_ENTERED" in events_log
    assert "D_EXITED" in events_log

def test_singleflight_follower_cancellation_does_not_cancel_leader():
    """
    P0-6 核心回归测试：
    Leader A 发起在飞计算，Follower B 与 Follower C 加入等待。
    Follower B 被 Cancel 绝不打断 Leader A，Leader A 与 Follower C 正常获得结果。
    """
    sf = SingleFlightLock()
    leader_started = threading.Event()
    leader_continue = threading.Event()
    call_count = 0

    async def heavy_calc():
        nonlocal call_count
        call_count += 1
        leader_started.set()
        while not leader_continue.is_set():
            await asyncio.sleep(0.01)
        return "LEADER_RESULT"

    results = {}
    errors = {}

    def thread_worker(name: str, cancel: bool = False):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            async def run():
                task = asyncio.create_task(sf.do("HEAVY_KEY", heavy_calc))
                if cancel:
                    await asyncio.sleep(0.02)
                    task.cancel()
                return await task
            results[name] = loop.run_until_complete(run())
        except BaseException as e:
            errors[name] = e
        finally:
            loop.close()

    t_a = threading.Thread(target=thread_worker, args=("A", False))
    t_b = threading.Thread(target=thread_worker, args=("B", True))
    t_c = threading.Thread(target=thread_worker, args=("C", False))

    t_a.start()
    leader_started.wait(timeout=2.0)
    t_b.start()
    t_c.start()

    time.sleep(0.05) # 让 B 触发 cancel
    leader_continue.set()

    t_a.join(timeout=3.0)
    t_b.join(timeout=3.0)
    t_c.join(timeout=3.0)

    # 核心断言：
    # 1. 真实计算仅执行了 1 次
    assert call_count == 1
    # 2. Leader A 正常拿到结果
    assert results["A"] == "LEADER_RESULT"
    # 3. Follower B 收到 CancelledError
    assert "B" in errors and isinstance(errors["B"], asyncio.CancelledError)
    # 4. Follower C 正常拿到结果
    assert results["C"] == "LEADER_RESULT"
    # 5. Key 安全释放
    assert "HEAVY_KEY" not in sf._calls

def test_singleflight_real_integration_with_parquet_manager(monkeypatch, tmp_path):
    """
    P0-3 真实跨线程/Event Loop 集成测试：
    通过真实 ParquetManager 与 SingleFlight，测试多线程跨 Event Loop 并发请求同一标的。
    断言外部 Adapter 仅被调用一次 (fetch count == 1)。
    """
    from storage.parquet_manager import ParquetManager
    from core.models import SymbolInfo, Market, AssetType, KlinePeriod
    from adapters.factory import adapter_factory
    from adapters.base import BaseDataSource
    import polars as pl

    pm = ParquetManager()
    info = SymbolInfo(
        symbol="SF_REAL.SH.STK",
        ticker="SF_REAL",
        market=Market.SH,
        asset_type=AssetType.STOCK,
        name="SingleFlight Real Stock",
        currency="CNY",
        is_benchmark=False
    )
    test_path = pm.get_file_path(info, "1d")
    if test_path.exists():
        test_path.unlink()

    fetch_call_count = 0
    fetch_started = threading.Event()
    fetch_release = threading.Event()

    class MockMultiThreadAdapter(BaseDataSource):
        def fetch_daily(self, info, start_date, end_date):
            nonlocal fetch_call_count
            fetch_call_count += 1
            fetch_started.set()
            fetch_release.wait(timeout=3.0)
            return pl.DataFrame({
                "timestamp": [1704182400000],
                "open": [10.0], "high": [10.0], "low": [10.0], "close": [10.0],
                "volume": [100.0], "amount": [1000.0], "factor": [1.0], "nav": [None]
            })
        def fetch_minute(self, *args, **kwargs): return None
        def fetch_snapshot(self, *args, **kwargs): return None
        def fetch_calendar(self, *args, **kwargs): return []
        def fetch_symbols(self, *args, **kwargs): return []

    monkeypatch.setattr(adapter_factory, "get_adapter", lambda m: MockMultiThreadAdapter())

    thread_results = {}
    thread_errors = {}

    def fetch_in_thread(tid: int):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            res = loop.run_until_complete(
                pm.get_or_fetch(info, KlinePeriod.D1, "2024-01-02", "2024-01-02")
            )
            thread_results[tid] = res
        except Exception as e:
            thread_errors[tid] = e
        finally:
            loop.close()

    t1 = threading.Thread(target=fetch_in_thread, args=(1,))
    t2 = threading.Thread(target=fetch_in_thread, args=(2,))
    t3 = threading.Thread(target=fetch_in_thread, args=(3,))

    t1.start()
    fetch_started.wait(timeout=2.0)
    t2.start()
    t3.start()

    time.sleep(0.05)
    fetch_release.set()

    t1.join(timeout=3.0)
    t2.join(timeout=3.0)
    t3.join(timeout=3.0)

    try:
        assert len(thread_errors) == 0, f"Thread errors: {thread_errors}"
        assert len(thread_results) == 3
        for i in (1, 2, 3):
            assert thread_results[i] is not None
            assert len(thread_results[i]) == 1
        # 核心断言：真实 Provider 仅被调用了 1 次！
        assert fetch_call_count == 1
    finally:
        if test_path.exists():
            test_path.unlink()

