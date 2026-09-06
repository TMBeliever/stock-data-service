import pytest
import time
import asyncio
from ai_core.session_manager import resolve_session_id, SessionManager
from ai_core.models import Message
from ai_core.config import ai_config

def test_resolve_session_id():
    # 1. 显式 session_id
    sid, is_ephem = resolve_session_id(explicit_session_id="custom-123")
    assert sid == "custom-123"
    assert not is_ephem

    # 2. 从 user 字段解析
    sid, is_ephem = resolve_session_id(user="user_alice")
    assert sid == "user_user_alice"
    assert not is_ephem

    # 3. 前缀指纹自适应 (模拟 Claude CLI / Cursor 发送无 session_id 的多轮消息)
    msgs_turn1 = [Message.user("Hello World, I am a quant trader")]
    sid1, is_ephem1 = resolve_session_id(messages=msgs_turn1)
    assert sid1.startswith("sess_")
    assert not is_ephem1

    # 第 2 轮追加新消息后，首条不变，指纹必须完全相同！
    msgs_turn2 = [
        Message.user("Hello World, I am a quant trader"),
        Message.assistant("Hello! Nice to meet you"),
        Message.user("Tell me about RSI")
    ]
    sid2, is_ephem2 = resolve_session_id(messages=msgs_turn2)
    assert sid2 == sid1  # 必须精确命中同一个会话！

    # 4. 不同的首条消息产生完全不同的会话指纹
    msgs_other = [Message.user("Different topic entirely")]
    sid_other, _ = resolve_session_id(messages=msgs_other)
    assert sid_other != sid1

@pytest.mark.asyncio
async def test_session_manager_lru_and_idle_sweep(monkeypatch):
    from ai_core.process_pool import PrewarmedProcess
    import sys

    mgr = SessionManager()
    monkeypatch.setattr(ai_config, "CLI_SESSION_MAX_WORKERS", 2)
    monkeypatch.setattr(ai_config, "CLI_SESSION_IDLE_TIMEOUT", 0.1)

    # 模拟 Worker
    async def mock_acquire(*args, **kwargs):
        p = await asyncio.create_subprocess_exec(
            sys.executable, "-c", "import sys; sys.stdin.read()",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        return PrewarmedProcess(proc=p, created_at=time.time())

    from ai_core.process_pool import prewarmed_process_pool
    monkeypatch.setattr(prewarmed_process_pool, "acquire_worker", mock_acquire)

    # 建立 2 个会话
    s1 = await mgr.get_or_create_session("sess_1")
    await asyncio.sleep(0.02)
    s2 = await mgr.get_or_create_session("sess_2")
    assert len(mgr._sessions) == 2

    # 触发 LRU 淘汰：创建第 3 个会话，最久未用的 sess_1 应被淘汰
    s3 = await mgr.get_or_create_session("sess_3")
    assert len(mgr._sessions) == 2
    assert "sess_1" not in mgr._sessions
    assert "sess_2" in mgr._sessions
    assert "sess_3" in mgr._sessions

    # 等待超过 0.1s 闲置后执行 sweep
    await asyncio.sleep(0.15)
    await mgr.sweep_expired_sessions()
    assert len(mgr._sessions) == 0

    await mgr.shutdown()
