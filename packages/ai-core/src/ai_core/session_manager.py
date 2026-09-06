import time
import uuid
import hashlib
import asyncio
import logging
from typing import Optional, List, Dict, Any, Tuple
from ai_core.config import ai_config
from ai_core.models import Message, ToolDefinition
from ai_core.process_pool import PrewarmedProcess, prewarmed_process_pool

logger = logging.getLogger(__name__)

def resolve_session_id(
    explicit_session_id: Optional[str] = None,
    messages: Optional[List[Message]] = None,
    user: Optional[str] = None
) -> Tuple[str, bool]:
    """
    智能解析会话标识符：
    1. 优先使用显式传入的 session_id；
    2. 其次使用客户端传递的 user 标识 (如 OpenAI user 字段)；
    3. 终极自适应：基于首条用户消息生成前缀指纹 (Prefix Fingerprint)，完全无感兼容 Claude CLI 等标准 Agent；
    4. 兜底生成一次性临时会话 ID。
    返回: (session_id, is_ephemeral)
    """
    if explicit_session_id and explicit_session_id.strip():
        return explicit_session_id.strip(), False

    if user and str(user).strip():
        return f"user_{str(user).strip()}", False

    if messages and len(messages) > 0:
        first_user = next((m for m in messages if m.role == "user" and m.content), None)
        if first_user and first_user.content and first_user.content.strip():
            fp = hashlib.sha256(first_user.content.strip().encode("utf-8")).hexdigest()[:16]
            return f"sess_{fp}", False

    return f"ephem_{uuid.uuid4().hex[:8]}", True

class SessionEntry:
    """单个会话的上下文与 Worker 状态追踪"""
    def __init__(self, session_id: str, worker: PrewarmedProcess):
        self.session_id: str = session_id
        self.worker: PrewarmedProcess = worker
        self.messages_processed: int = 0
        self.created_at: float = time.time()
        self.last_active: float = time.time()
        self.lock = asyncio.Lock()

class SessionManager:
    """
    会话粘性 Worker 管理器 (Session-Sticky Worker Manager):
    1. 粘性绑定：为多轮交互的 Agent 绑定专属 Worker，彻底杜绝会话串扰与冷启动；
    2. 增量裁剪：对比历史条数，只发送最新 delta 消息，彻底杜绝外部 Agent 发全量导致上下文翻倍；
    3. 自动回收：LRU 淘汰与空闲 TTL 巡检，防止 Worker 长期占用 VPS 内存。
    """
    def __init__(self):
        self._sessions: Dict[str, SessionEntry] = {}
        self._lock = asyncio.Lock()
        self._sweeper_task: Optional[asyncio.Task] = None

    def start(self):
        """启动后台空闲会话巡检任务"""
        if self._sweeper_task is None or self._sweeper_task.done():
            self._sweeper_task = asyncio.create_task(self._sweep_loop())

    async def shutdown(self):
        """关闭并清理所有会话及绑定的 Worker"""
        if self._sweeper_task and not self._sweeper_task.done():
            self._sweeper_task.cancel()
            try:
                await self._sweeper_task
            except asyncio.CancelledError:
                pass

        async with self._lock:
            entries = list(self._sessions.values())
            self._sessions.clear()

        for entry in entries:
            try:
                await entry.worker.terminate()
            except Exception as e:
                logger.debug(f"[SessionManager] 销毁 Worker 异常: {e}")
        logger.info("[SessionManager] 已释放所有粘性会话 Worker 资源。")

    async def _sweep_loop(self):
        """定期扫描过期闲置会话"""
        while True:
            try:
                await asyncio.sleep(30.0)
                await self.sweep_expired_sessions()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[SessionManager] 巡检异常: {e}")

    async def sweep_expired_sessions(self):
        """清理超过闲置 TTL 的会话"""
        now = time.time()
        ttl = ai_config.CLI_SESSION_IDLE_TIMEOUT
        expired_entries: List[SessionEntry] = []

        async with self._lock:
            for sid, entry in list(self._sessions.items()):
                if now - entry.last_active > ttl:
                    expired_entries.append(entry)
                    del self._sessions[sid]

        for entry in expired_entries:
            logger.info(
                f"[SessionManager] ⏱️ 会话 {entry.session_id} 闲置超过 {ttl}s，"
                f"回收释放 Worker (PID {entry.worker.proc.pid})"
            )
            asyncio.create_task(prewarmed_process_pool.release_worker(entry.worker))

    async def get_or_create_session(
        self,
        session_id: str,
        executable: Optional[str] = None,
        model: Optional[str] = None,
        effort: Optional[str] = None,
        env: Optional[Dict[str, str]] = None
    ) -> SessionEntry:
        """获取或创建粘性会话条目"""
        async with self._lock:
            entry = self._sessions.get(session_id)
            if entry is not None:
                if entry.worker.is_alive and entry.worker.is_ready:
                    entry.last_active = time.time()
                    return entry
                else:
                    logger.warning(f"[SessionManager] 会话 {session_id} 的 Worker 已失效，重新分配")
                    try:
                        await prewarmed_process_pool.release_worker(entry.worker)
                    except Exception:
                        pass
                    del self._sessions[session_id]

            if len(self._sessions) >= ai_config.CLI_SESSION_MAX_WORKERS:
                oldest_sid = min(self._sessions.keys(), key=lambda k: self._sessions[k].last_active)
                oldest_entry = self._sessions.pop(oldest_sid)
                logger.info(f"[SessionManager] 达到会话上限 ({ai_config.CLI_SESSION_MAX_WORKERS})，LRU 回收 {oldest_sid}")
                asyncio.create_task(prewarmed_process_pool.release_worker(oldest_entry.worker))

            worker = await prewarmed_process_pool.acquire_worker(
                executable=executable,
                model=model,
                effort=effort,
                env=env
            )
            entry = SessionEntry(session_id=session_id, worker=worker)
            self._sessions[session_id] = entry
            logger.info(
                f"[SessionManager] 绑定新会话 {session_id} -> Worker PID {worker.proc.pid} "
                f"(model={worker.model}, effort={worker.effort})"
            )
            return entry

    async def close_session(self, session_id: str):
        """显式关闭指定会话并销毁 Worker"""
        async with self._lock:
            entry = self._sessions.pop(session_id, None)
        if entry:
            logger.info(f"[SessionManager] 显式关闭会话 {session_id}，释放 Worker PID {entry.worker.proc.pid}")
            await prewarmed_process_pool.release_worker(entry.worker)

    def get_status(self) -> Dict[str, Any]:
        """查看当前所有粘性会话与 Worker 状态诊断"""
        now = time.time()
        sessions_info = []
        for sid, e in self._sessions.items():
            sessions_info.append({
                "session_id": sid,
                "pid": e.worker.proc.pid if e.worker.proc else None,
                "model": e.worker.model,
                "effort": e.worker.effort,
                "messages_processed": e.messages_processed,
                "idle_seconds": round(now - e.last_active, 1),
                "is_alive": e.worker.is_alive
            })
        return {
            "active_sessions_count": len(self._sessions),
            "max_sessions_allowed": ai_config.CLI_SESSION_MAX_WORKERS,
            "idle_timeout_s": ai_config.CLI_SESSION_IDLE_TIMEOUT,
            "sessions": sessions_info
        }

session_manager = SessionManager()
