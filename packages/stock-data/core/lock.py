import asyncio
import concurrent.futures
import threading
from typing import Dict, Any, Callable, Coroutine, List
from contextlib import asynccontextmanager

class SingleFlightLock:
    """
    跨线程与跨 Event Loop 安全的标的级单飞锁与请求合并器 (SingleFlight & Request Coalescing)：
    1. 使用 threading.Lock() 保护内部状态字典，杜绝 asyncio.Lock 跨 Loop 导致的
       'RuntimeError: Lock is bound to a different event loop'；
    2. 采用 concurrent.futures.Future 跨 Loop 兼容底座，配合 asyncio.wrap_future，
       天然支持任意多线程与多事件循环并发请求的无损合并与唤醒，绝不报
       'Future attached to different loop'；
    3. 支持 Leader/Follower 异常与取消隔离，防止死锁与状态残留。
    """
    def __init__(self):
        self._calls: Dict[str, concurrent.futures.Future] = {}
        self._key_holders: Dict[str, Any] = {}
        self._key_waiters: Dict[str, List[concurrent.futures.Future]] = {}
        self._mutex = threading.Lock()

    def _wake_next_waiter(self, key: str):
        """唤醒指定 key 的下一个有效等待者，跳过已取消或已完成的无效 Future (必须在 self._mutex 锁内调用)"""
        while key in self._key_waiters and self._key_waiters[key]:
            next_fut = self._key_waiters[key].pop(0)
            if not next_fut.done() and not next_fut.cancelled():
                try:
                    next_fut.set_result(True)
                    return  # 成功唤醒下一个有效 waiter
                except Exception:
                    continue  # 若该 waiter 异常，继续唤醒下一个

        # 队列为空或已无有效 waiter，彻底释放锁持有者状态
        self._key_holders.pop(key, None)
        self._key_waiters.pop(key, None)

    @asynccontextmanager
    async def acquire(self, key: str):
        """
        标的级排他执行锁 (跨线程与跨 Event Loop 安全)：
        支持 Waiter 取消弹性自愈，绝不因某个 Waiter 取消而导致后续 Waiter 永久死锁。
        """
        fut = None
        with self._mutex:
            if key not in self._key_holders:
                self._key_holders[key] = object()
            else:
                fut = concurrent.futures.Future()
                if key not in self._key_waiters:
                    self._key_waiters[key] = []
                self._key_waiters[key].append(fut)

        if fut is not None:
            try:
                await asyncio.wrap_future(fut)
            except BaseException:
                # 等待过程中被外部 Task 取消或发生异常
                with self._mutex:
                    # 1. 若当前 fut 仍在等待队列中，直接剔除，避免后续虚假弹出
                    if key in self._key_waiters and fut in self._key_waiters[key]:
                        self._key_waiters[key].remove(fut)
                    # 2. 若在此瞬间前一个持有者已将执行权赋给了当前 fut (fut.done() == True)，
                    # 则当前取消的任务必须负责把执行权顺延给下一个有效 waiter！
                    if fut.done() and not fut.cancelled():
                        self._wake_next_waiter(key)
                raise

        try:
            yield
        finally:
            with self._mutex:
                self._wake_next_waiter(key)

    async def do(self, key: str, fn: Callable[[], Coroutine[Any, Any, Any]]) -> Any:
        """
        Request Coalescing 核心执行：
        如果同一个 key 已有请求在执行中，其余并发请求 (即使来自不同线程或不同 event loop)
        均通过底层跨循环 Future 共享并等待同一计算结果返回。
        """
        with self._mutex:
            if key in self._calls:
                cf_future = self._calls[key]
                is_leader = False
            else:
                cf_future = concurrent.futures.Future()
                self._calls[key] = cf_future
                is_leader = True

        if not is_leader:
            loop_fut = asyncio.wrap_future(cf_future)
            return await asyncio.shield(loop_fut)

        try:
            res = await fn()
            if not cf_future.done():
                cf_future.set_result(res)
            return res
        except BaseException as e:
            if not cf_future.done():
                cf_future.set_exception(e)
            raise
        finally:
            with self._mutex:
                if key in self._calls and self._calls[key] is cf_future:
                    del self._calls[key]

single_flight = SingleFlightLock()
