import threading
from typing import Dict
from collections import OrderedDict
from contextlib import contextmanager

class StorageLockManager:
    """
    单机轻量级存储文件互斥锁，协调 ParquetManager 写入与 Sentinel LRU 淘汰清理，
    杜绝并发读写与删除竞态。
    锁表采用 LRU 上限约束，避免长期运行因新增文件路径导致内存无限膨胀。
    """
    def __init__(self, max_locks: int = 4096):
        self._locks: "OrderedDict[str, threading.Lock]" = OrderedDict()
        self._global_lock = threading.Lock()
        self._max_locks = max_locks

    def _get_or_create(self, key: str) -> threading.Lock:
        with self._global_lock:
            lock = self._locks.get(key)
            if lock is not None:
                # 命中后移动到末尾，保证 LRU 淘汰顺序正确
                self._locks.move_to_end(key)
                return lock
            lock = threading.Lock()
            self._locks[key] = lock
            # 超过容量上限时淘汰最久未使用的锁
            while len(self._locks) > self._max_locks:
                self._locks.popitem(last=False)
            return lock

    @contextmanager
    def lock(self, path_or_key: str):
        key = str(path_or_key)
        target_lock = self._get_or_create(key)

        target_lock.acquire()
        try:
            yield
        finally:
            target_lock.release()

storage_locks = StorageLockManager()
