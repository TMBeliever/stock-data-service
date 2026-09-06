import os
import time
import uuid
import shutil
import asyncio
import logging
from typing import Optional, Dict, Any, List, AsyncGenerator
from ai_core.config import ai_config
from ai_core.models import Message, StreamChunk, AIResponse

logger = logging.getLogger(__name__)

def ensure_writable_gemini_environment():
    """
    确保容器内 /root/.gemini 与 /root/.antigravity 目录具备真实写权限：
    若此前存在指向宿主机只读目录的软链接，则安全迁移为真实目录，
    并将宿主机的认证凭据复制过来，保留 conversations、log、cache 具有读写能力，
    彻底消除 'read-only file system' 错误，保障会话数据库正常持久化。
    """
    import glob
    for config_name in [".gemini", ".antigravity"]:
        container_dir = f"/root/{config_name}"
        host_candidates = [
            f"/host_root/{config_name}",
        ] + glob.glob(f"/host_home/*/{config_name}")

        try:
            if os.path.islink(container_dir):
                os.unlink(container_dir)

            if not os.path.exists(container_dir):
                os.makedirs(container_dir, exist_ok=True)

            for host_dir in host_candidates:
                if os.path.exists(host_dir):
                    for item in os.listdir(host_dir):
                        s = os.path.join(host_dir, item)
                        d = os.path.join(container_dir, item)
                        if not os.path.exists(d):
                            if os.path.isdir(s):
                                try:
                                    shutil.copytree(s, d, symlinks=True)
                                except Exception:
                                    pass
                            else:
                                try:
                                    shutil.copy2(s, d)
                                except Exception:
                                    pass
        except Exception as e:
            logger.debug(f"[SessionManager] 初始化 {config_name} 写目录提示: {e}")

class SessionWorker:
    """
    会话级独立 Worker：
    负责管理单一客户端/用户会话的执行管道、对话记忆与活跃度。
    """
    def __init__(self, session_id: str):
        self.session_id: str = session_id
        # 为当前会话生成确定性或专属的 UUID，供底层 agy 的 --conversation 保持记忆
        self.conversation_uuid: str = str(uuid.uuid5(uuid.NAMESPACE_DNS, session_id))
        self.created_at: float = time.time()
        self.last_active_at: float = time.time()
        self.turn_count: int = 0
        self.lock: asyncio.Lock = asyncio.Lock()
        self._current_proc: Optional[asyncio.subprocess.Process] = None

    def touch(self):
        """刷新活跃时间戳"""
        self.last_active_at = time.time()

    async def terminate(self):
        """优雅关闭或终止当前正在运行的任何子进程"""
        if self._current_proc and self._current_proc.returncode is None:
            try:
                self._current_proc.terminate()
                await asyncio.wait_for(self._current_proc.wait(), timeout=2.0)
            except Exception:
                try:
                    self._current_proc.kill()
                except Exception:
                    pass
        self._current_proc = None

class SessionWorkerManager:
    """
    会话亲和性惰性温备单例管理器 (Session-Affinity Lazy Warm Worker Manager)：
    1. 为每个活跃 session_id 分配专属 Worker；
    2. 定时巡检自毁闲置超过 5 分钟 (TTL) 的会话，VPS 内存自动归零 (Scale-to-Zero)；
    3. 支持最大并发会话淘汰 (LRU) 与优雅关机全量回收。
    """
    def __init__(self):
        self._workers: Dict[str, SessionWorker] = {}
        self._manager_lock = asyncio.Lock()
        self._sweeper_task: Optional[asyncio.Task] = None

    def start_sweeper(self):
        """启动后台空闲会话定时巡检回收协程"""
        ensure_writable_gemini_environment()
        if self._sweeper_task is None or self._sweeper_task.done():
            self._sweeper_task = asyncio.create_task(self._sweep_loop())

    async def stop_sweeper(self):
        """停止后台巡检并清理所有存活会话"""
        if self._sweeper_task and not self._sweeper_task.done():
            self._sweeper_task.cancel()
            try:
                await self._sweeper_task
            except asyncio.CancelledError:
                pass
        await self.shutdown_all()

    async def _sweep_loop(self):
        """后台定时轮询循环"""
        while True:
            try:
                await asyncio.sleep(ai_config.CLI_SESSION_SWEEP_INTERVAL)
                await self.sweep_expired_workers()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[SessionWorkerManager] 巡检异常: {e}")

    async def sweep_expired_workers(self):
        """扫描并回收闲置超时的会话"""
        now = time.time()
        ttl = ai_config.CLI_SESSION_TTL
        expired_ids: List[str] = []

        async with self._manager_lock:
            for sid, worker in list(self._workers.items()):
                if now - worker.last_active_at > ttl:
                    expired_ids.append(sid)

        for sid in expired_ids:
            await self.cleanup_session(sid)
            logger.info(f"[SessionWorkerManager] 会话 '{sid}' 闲置超时超过 {ttl}s，已自动回收释放内存。")

    async def get_or_create_worker(self, session_id: str) -> SessionWorker:
        """获取或创建与指定会话绑定的专属 Worker"""
        ensure_writable_gemini_environment()
        async with self._manager_lock:
            if session_id in self._workers:
                worker = self._workers[session_id]
                worker.touch()
                return worker

            # 超过最大温备数量时，淘汰最久未活跃的会话 (LRU)
            if len(self._workers) >= ai_config.CLI_MAX_ACTIVE_SESSIONS:
                oldest_sid = min(self._workers.keys(), key=lambda k: self._workers[k].last_active_at)
                oldest_worker = self._workers.pop(oldest_sid, None)
                if oldest_worker:
                    asyncio.create_task(oldest_worker.terminate())
                    logger.info(f"[SessionWorkerManager] 达到并发温存上限，LRU 淘汰会话 '{oldest_sid}'")

            worker = SessionWorker(session_id)
            self._workers[session_id] = worker
            logger.info(f"[SessionWorkerManager] 初始化新温备会话 Worker: '{session_id}' (conversation_uuid: {worker.conversation_uuid})")
            return worker

    async def cleanup_session(self, session_id: str):
        """主动清理指定会话"""
        async with self._manager_lock:
            worker = self._workers.pop(session_id, None)
        if worker:
            await worker.terminate()

    async def shutdown_all(self):
        """服务停止时全量释放所有会话资源"""
        async with self._manager_lock:
            workers = list(self._workers.values())
            self._workers.clear()

        for w in workers:
            await w.terminate()
        logger.info("[SessionWorkerManager] 已释放所有温备会话。")

# 全局单例
session_worker_manager = SessionWorkerManager()
