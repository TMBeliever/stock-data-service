import sys
import asyncio
import time
import pytest
from ai_core.process_pool import PrewarmedProcess, PrewarmedProcessPool
from ai_core.config import ai_config
from ai_core.models import Message

@pytest.mark.asyncio
async def test_prewarmed_process_execute_and_stream():
    """测试单个 PrewarmedProcess 能够通过 stdin 接收输入，流式吐出输出，并且单次使用后彻底关闭"""
    # 模拟一个执行 echo 的 Python 子进程
    code = (
        "import sys\n"
        "data = sys.stdin.read().strip()\n"
        "print('PROCESSED_' + data, flush=True)\n"
    )
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-c", code,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )

    worker = PrewarmedProcess(proc=proc, created_at=time.time())
    assert worker.is_alive

    chunks = []
    async for chunk in worker.execute_and_stream("TEST_INPUT", timeout=5.0):
        if chunk.delta:
            chunks.append(chunk.delta)

    full_output = "".join(chunks)
    assert "PROCESSED_TEST_INPUT" in full_output
    assert not worker.is_alive  # 执行完毕后进程已退出

@pytest.mark.asyncio
async def test_process_pool_atomic_lease_and_physical_isolation(monkeypatch):
    """测试并发调用时，每个请求从池中原子独占获取不同 PID 的完全隔离进程"""
    pool = PrewarmedProcessPool()
    monkeypatch.setattr(ai_config, "CLI_STANDBY_POOL_SIZE", 2)
    monkeypatch.setattr(ai_config, "CLI_MAX_CONCURRENCY", 4)
    monkeypatch.setattr(ai_config, "CLI_SPAWN_STAGGER_DELAY", 0.05)

    # 模拟生成 mock 进程
    async def mock_spawn(*args, **kwargs):
        p = await asyncio.create_subprocess_exec(
            sys.executable, "-c", "import sys, time; sys.stdin.read(); sys.exit(0)",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        return PrewarmedProcess(proc=p, created_at=time.time())

    monkeypatch.setattr(pool, "_spawn_worker", mock_spawn)

    # 并发请求 1 和请求 2 同时索取 Worker
    w1, w2 = await asyncio.gather(
        pool.acquire_worker(),
        pool.acquire_worker()
    )

    try:
        assert w1 is not w2
        # 物理级隔离：两个请求拥有完全不同的操作系统 PID
        assert w1.proc.pid != w2.proc.pid
        assert w1.leased is True
        assert w2.leased is True
    finally:
        await pool.release_worker(w1)
        await pool.release_worker(w2)
        await pool.shutdown()

@pytest.mark.asyncio
async def test_process_pool_single_use_terminate(monkeypatch):
    """测试请求结束后 Worker 被彻底杀死 (用完即焚)，绝不复用以防状态污染"""
    pool = PrewarmedProcessPool()
    monkeypatch.setattr(ai_config, "CLI_SPAWN_STAGGER_DELAY", 0.05)

    async def mock_spawn(*args, **kwargs):
        p = await asyncio.create_subprocess_exec(
            sys.executable, "-c", "import sys, time; sys.stdin.read(); sys.exit(0)",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        return PrewarmedProcess(proc=p, created_at=time.time())

    monkeypatch.setattr(pool, "_spawn_worker", mock_spawn)

    worker = await pool.acquire_worker()
    assert worker.is_alive

    # 释放 worker
    await pool.release_worker(worker)
    assert not worker.is_alive  # 确认已经物理死亡
    assert worker not in pool._active_processes
    await pool.shutdown()

@pytest.mark.asyncio
async def test_process_pool_idle_scale_to_zero(monkeypatch):
    """测试闲置超过设定时间后自动清空待命进程，实现内存归零 (Scale-to-Zero)"""
    pool = PrewarmedProcessPool()
    monkeypatch.setattr(ai_config, "CLI_STANDBY_POOL_SIZE", 2)
    monkeypatch.setattr(ai_config, "CLI_POOL_IDLE_TIMEOUT", 0.05)
    monkeypatch.setattr(ai_config, "CLI_SPAWN_STAGGER_DELAY", 0.01)

    async def mock_spawn(*args, **kwargs):
        p = await asyncio.create_subprocess_exec(
            sys.executable, "-c", "import sys; sys.stdin.read()",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        return PrewarmedProcess(proc=p, created_at=time.time())

    monkeypatch.setattr(pool, "_spawn_worker", mock_spawn)

    # 模拟加入 2 个预热进程
    w1 = await mock_spawn()
    w2 = await mock_spawn()
    await pool._standby_queue.put(w1)
    await pool._standby_queue.put(w2)
    pool._is_active = True
    assert pool._standby_queue.qsize() == 2

    # 等待超过 IDLE_TIMEOUT 并触发巡检
    await asyncio.sleep(0.08)
    await pool.sweep_idle()

    # 待命队列已被彻底清空，内存归零
    assert pool._standby_queue.empty()
    assert not w1.is_alive
    assert not w2.is_alive
    assert not pool._is_active
    await pool.shutdown()

@pytest.mark.asyncio
async def test_process_pool_staggered_gentle_warmup(monkeypatch):
    """测试 4 个待命进程温和错峰启动，每次启动之间有延迟，不会瞬间打满 CPU"""
    pool = PrewarmedProcessPool()
    monkeypatch.setattr(ai_config, "CLI_STANDBY_POOL_SIZE", 4)
    monkeypatch.setattr(ai_config, "CLI_MAX_CONCURRENCY", 8)
    monkeypatch.setattr(ai_config, "CLI_SPAWN_STAGGER_DELAY", 0.05)

    spawn_timestamps = []
    async def mock_spawn(*args, **kwargs):
        spawn_timestamps.append(time.time())
        p = await asyncio.create_subprocess_exec(
            sys.executable, "-c", "import sys; sys.stdin.read()",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        return PrewarmedProcess(proc=p, created_at=time.time())

    monkeypatch.setattr(pool, "_spawn_worker", mock_spawn)

    # 模拟首个请求触发激活
    worker = await pool.acquire_worker()
    assert worker.is_alive

    # 等待后台温和错峰把剩余待命补齐到 4 个
    # 3 个待命 * 0.05s = 约 0.15s
    await asyncio.sleep(0.3)
    assert pool._standby_queue.qsize() == 4

    # 验证拉起时间戳具有错峰间隔，杜绝瞬间并发拉起
    assert len(spawn_timestamps) >= 4
    for i in range(1, len(spawn_timestamps)):
        gap = spawn_timestamps[i] - spawn_timestamps[i-1]
        assert gap >= 0.03, f"进程 {i} 与 {i-1} 间隔过短: {gap}s"

    await pool.release_worker(worker)
    await pool.shutdown()

@pytest.mark.asyncio
async def test_process_pool_four_workers_concurrent(monkeypatch):
    """测试 4 个并发请求同时打入，4 个 Worker 各自独立执行，结果绝无串扰"""
    pool = PrewarmedProcessPool()
    monkeypatch.setattr(ai_config, "CLI_STANDBY_POOL_SIZE", 4)
    monkeypatch.setattr(ai_config, "CLI_MAX_CONCURRENCY", 4)

    # 每个子进程独立根据 stdin 加上自己的前缀
    async def mock_spawn(*args, **kwargs):
        code = (
            "import sys\n"
            "data = sys.stdin.read().strip()\n"
            "print(f'OUTPUT_{data}', flush=True)\n"
        )
        p = await asyncio.create_subprocess_exec(
            sys.executable, "-c", code,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        return PrewarmedProcess(proc=p, created_at=time.time())

    monkeypatch.setattr(pool, "_spawn_worker", mock_spawn)

    async def run_single_request(client_id: str) -> str:
        w = await pool.acquire_worker()
        try:
            return await w.execute(f"REQ_{client_id}", timeout=5.0)
        finally:
            await pool.release_worker(w)

    # 4 个并发第三方请求同时调用
    results = await asyncio.gather(
        run_single_request("1"),
        run_single_request("2"),
        run_single_request("3"),
        run_single_request("4")
    )

    # 严格验证每个请求拿到的都是完全属于自己的独立结果，绝对无串扰
    assert results[0] == "OUTPUT_REQ_1"
    assert results[1] == "OUTPUT_REQ_2"
    assert results[2] == "OUTPUT_REQ_3"
    assert results[3] == "OUTPUT_REQ_4"

    await pool.shutdown()

@pytest.mark.asyncio
async def test_process_pool_client_interrupt_and_retry(monkeypatch):
    """测试客户端中途打断请求 (Ctrl+C / CancelledError) 后，进程被彻底杀死且重试时无残留污染"""
    pool = PrewarmedProcessPool()
    monkeypatch.setattr(ai_config, "CLI_STANDBY_POOL_SIZE", 2)
    monkeypatch.setattr(ai_config, "CLI_MAX_CONCURRENCY", 4)
    monkeypatch.setattr(ai_config, "CLI_SPAWN_STAGGER_DELAY", 0.05)

    async def mock_spawn(*args, **kwargs):
        code = (
            "import sys, time\n"
            "data = sys.stdin.read().strip()\n"
            "time.sleep(0.5)\n"
            "print('RES_' + data, flush=True)\n"
        )
        p = await asyncio.create_subprocess_exec(
            sys.executable, "-c", code,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        return PrewarmedProcess(proc=p, created_at=time.time())

    monkeypatch.setattr(pool, "_spawn_worker", mock_spawn)

    # 1. 模拟第一个请求启动后，客户端中途打断 (Cancel)
    worker1 = await pool.acquire_worker()
    pid1 = worker1.proc.pid
    assert worker1 in pool._active_processes

    # 模拟客户端断开连接触发 CancelledError，finally 释放
    try:
        raise asyncio.CancelledError("User pressed Ctrl+C in Claude CLI")
    except asyncio.CancelledError:
        await pool.release_worker(worker1)

    # 验证 worker1 已经被立即杀死并移出活跃集合
    assert worker1 not in pool._active_processes
    # 等待进程退出
    await asyncio.sleep(0.1)
    assert not worker1.is_alive

    # 2. 模拟客户端紧接着重新发起请求
    worker2 = await pool.acquire_worker()
    pid2 = worker2.proc.pid
    assert pid2 != pid1  # 必须是全新独立的子进程

    try:
        res = await worker2.execute("CLEAN_RETRY_PROMPT", timeout=5.0)
        assert "RES_CLEAN_RETRY_PROMPT" in res
    finally:
        await pool.release_worker(worker2)

    await pool.shutdown()

@pytest.mark.asyncio
async def test_process_pool_spawn_worker_args(monkeypatch):
    """验证 _spawn_worker 针对 agy 工具生成合规参数：使用 --dangerously-skip-permissions 和 --model，绝不传 -y 和 -m"""
    pool = PrewarmedProcessPool()
    captured_cmds = []

    orig_exec = asyncio.create_subprocess_exec

    async def mock_create_subprocess_exec(*args, **kwargs):
        captured_cmds.append(list(args))
        # 模拟启动一个 dummy python 进程
        return await orig_exec(
            sys.executable, "-c", "import sys; sys.exit(0)",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

    monkeypatch.setattr(asyncio, "create_subprocess_exec", mock_create_subprocess_exec)

    # 1. 针对 agy
    w1 = await pool._spawn_worker(executable="agy", model="claude-sonnet-4.6")
    cmd1 = captured_cmds[-1]
    assert "--dangerously-skip-permissions" in cmd1
    assert "--model" in cmd1
    assert "claude-sonnet-4.6" in cmd1
    assert "-y" not in cmd1
    assert "-m" not in cmd1
    assert "-p" not in cmd1

    # 2. 针对 gemini
    w2 = await pool._spawn_worker(executable="gemini", model="gemini-3.8-flash")
    cmd2 = captured_cmds[-1]
    assert "-p" in cmd2
    assert "-y" in cmd2
    assert "--model" in cmd2
    assert "--dangerously-skip-permissions" not in cmd2

    await w1.terminate()
    await w2.terminate()



