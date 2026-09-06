import os
import time
import shutil
import asyncio
import logging
import glob
from typing import Optional, List, Dict, Set, AsyncGenerator

from ai_core.config import ai_config
from ai_core.models import StreamChunk

logger = logging.getLogger(__name__)

def ensure_writable_gemini_environment():
    """
    确保容器内 /root/.gemini 与 /root/.antigravity 目录具备真实写权限：
    解除指向宿主机只读目录的软链接，并将宿主机认证凭据安全复制至容器 overlayfs 可写层，
    彻底消除 'read-only file system' 错误。
    """
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
            logger.debug(f"[ProcessPool] 初始化 {config_name} 写目录提示: {e}")

class PrewarmedProcess:
    """
    预热就绪的独占进程：
    在后台提前拉起并加载完 Node 虚拟机与依赖，只等写入 stdin 输入；
    一次性使用（Single-Use），推演结束后彻底杀死，绝不跨请求复用，100% 杜绝串流与状态残留。
    """
    def __init__(self, proc: asyncio.subprocess.Process, created_at: float, model: Optional[str] = None):
        self.proc: asyncio.subprocess.Process = proc
        self.created_at: float = created_at
        self.model: Optional[str] = model
        self.leased: bool = False

    @property
    def is_alive(self) -> bool:
        return self.proc.returncode is None

    async def execute_and_stream(self, prompt: str, timeout: float = 120.0) -> AsyncGenerator[StreamChunk, None]:
        """独占通过 stdin 写入当前完整上下文，流式从 stdout 读取生成文本"""
        # 1. 写入 stdin 管道并关闭输入 (发出 EOF 触发大模型开始推演)
        try:
            if self.proc.stdin:
                self.proc.stdin.write(prompt.encode("utf-8"))
                await self.proc.stdin.drain()
                self.proc.stdin.close()
        except Exception as e:
            logger.error(f"[PrewarmedProcess] 写入 stdin 异常: {e}")
            raise

        # 2. 逐行读取 stdout 产出 Token
        async def read_stream():
            if not self.proc.stdout:
                return
            while True:
                line = await self.proc.stdout.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace")
                yield StreamChunk(delta=text, role="assistant")

        try:
            async for chunk in read_stream():
                yield chunk

            await asyncio.wait_for(self.proc.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            try:
                self.proc.kill()
            except Exception:
                pass
            raise TimeoutError(f"[PrewarmedProcess] 进程执行超时 (超限 {timeout}s)")

        if self.proc.returncode != 0:
            stderr_bytes = await self.proc.stderr.read() if self.proc.stderr else b""
            err = stderr_bytes.decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"[PrewarmedProcess] 进程异常退出 ({self.proc.returncode}): {err}")

        yield StreamChunk(finish_reason="stop")

    async def execute(self, prompt: str, timeout: float = 120.0) -> str:
        """非流式：等待完整推演并返回文本"""
        chunks = []
        async for chunk in self.execute_and_stream(prompt, timeout=timeout):
            if chunk.delta:
                chunks.append(chunk.delta)
        return "".join(chunks).strip()

    async def terminate(self):
        """用完即焚：彻底杀死进程释放资源"""
        if self.proc.returncode is None:
            try:
                if self.proc.stdin and not self.proc.stdin.is_closing():
                    self.proc.stdin.close()
            except Exception:
                pass
            try:
                self.proc.terminate()
                await asyncio.wait_for(self.proc.wait(), timeout=1.0)
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass

class PrewarmedProcessPool:
    """
    独占预热待命进程池 (Pre-warmed Standby Process Pool):
    1. 彻底无状态 (100% Stateless)：不存任何会话数据库，不传 --conversation，每个请求独占一次性进程；
    2. 物理级管道隔离：独立进程独立管道，并发绝不粘包、绝不串流；
    3. 温和错峰启动 (Gentle Warmup)：请求激活后，每个待命进程之间间隔 2 秒错峰拉起，杜绝 CPU 瞬间打满；
    4. 自动补位：借走一个立即异步温和补充一个，维持 4 个待命战斗力；
    5. 空闲归零 (Scale-to-Zero)：5 分钟内无请求自动释放所有待命进程，服务器内存彻底归零。
    """
    def __init__(self):
        self._standby_queue: asyncio.Queue[PrewarmedProcess] = asyncio.Queue(
            maxsize=ai_config.CLI_STANDBY_POOL_SIZE
        )
        self._semaphore = asyncio.Semaphore(ai_config.CLI_MAX_CONCURRENCY)
        self._active_processes: Set[PrewarmedProcess] = set()
        self._lock = asyncio.Lock()
        self._is_active: bool = False
        self._last_request_time: float = time.time()
        self._sweeper_task: Optional[asyncio.Task] = None
        self._fill_task: Optional[asyncio.Task] = None

    def start(self):
        """启动后台空闲巡检回收协程"""
        ensure_writable_gemini_environment()
        if self._sweeper_task is None or self._sweeper_task.done():
            self._sweeper_task = asyncio.create_task(self._sweep_loop())

    async def shutdown(self):
        """服务关闭：取消所有后台任务并清空全部待命进程与运行中进程"""
        if self._sweeper_task and not self._sweeper_task.done():
            self._sweeper_task.cancel()
            try:
                await self._sweeper_task
            except asyncio.CancelledError:
                pass

        if self._fill_task and not self._fill_task.done():
            self._fill_task.cancel()
            try:
                await self._fill_task
            except asyncio.CancelledError:
                pass

        await self.clear_standby()

        async with self._lock:
            active = list(self._active_processes)
            self._active_processes.clear()

        for w in active:
            await w.terminate()
        logger.info("[ProcessPool] 已释放所有进程池资源。")

    async def _sweep_loop(self):
        """后台轮询，检测闲置 5 分钟自动释放"""
        while True:
            try:
                await asyncio.sleep(15.0)
                await self.sweep_idle()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[ProcessPool] 巡检异常: {e}")

    async def sweep_idle(self):
        """闲置超过指定 TTL 则销毁待命队列进程 (Scale-to-Zero)"""
        now = time.time()
        if self._is_active and (now - self._last_request_time > ai_config.CLI_POOL_IDLE_TIMEOUT):
            logger.info(
                f"[ProcessPool] 闲置超过 {ai_config.CLI_POOL_IDLE_TIMEOUT}s，"
                f"清空 {self._standby_queue.qsize()} 个待命进程，VPS 内存归零。"
            )
            if self._fill_task and not self._fill_task.done():
                self._fill_task.cancel()
            await self.clear_standby()
            self._is_active = False

    async def clear_standby(self):
        """清空待命队列中的全部进程"""
        while not self._standby_queue.empty():
            try:
                worker = self._standby_queue.get_nowait()
                await worker.terminate()
            except asyncio.QueueEmpty:
                break

    async def _spawn_worker(
        self,
        executable: Optional[str] = None,
        model: Optional[str] = None,
        env: Optional[Dict[str, str]] = None
    ) -> PrewarmedProcess:
        """底层拉起一个新的预热待命子进程"""
        from ai_core.providers.cli_provider import resolve_executable_path
        ensure_writable_gemini_environment()

        exe = resolve_executable_path(executable or ai_config.CLI_EXECUTABLE)

        # 构造纯净无状态参数：彻底禁用工具执行，严禁添加 --conversation / -c / -r
        cmd_args = [exe]
        exe_lower = os.path.basename(exe).lower()
        if "gemini" in exe_lower:
            cmd_args.extend(["-p", "", "-y"])
        else:
            # Google agy (Go 二进制) 与 Claude CLI 均使用 --dangerously-skip-permissions
            # 严禁传 -y 和 -m，且走 stdin 管道通信时严禁传空 prompt ("-p", "")，否则 agy 校验失败直接退出
            cmd_args.append("--dangerously-skip-permissions")

        if model:
            # agy / gemini / claude 均原生支持 --model 参数 (agy 不支持 -m 缩写)
            cmd_args.extend(["--model", model])

        # 运行在干净隔离的临时工作区目录，杜绝扫描当前代码库与 git
        isolated_cwd = "/tmp/quant_ai_clean_sandbox"
        os.makedirs(isolated_cwd, exist_ok=True)

        merged_env = os.environ.copy()
        if env:
            merged_env.update(env)
        merged_env["NO_COLOR"] = "1"
        if os.path.exists("/root/.gemini"):
            merged_env["GEMINI_CONFIG_DIR"] = "/root/.gemini"

        proc = await asyncio.create_subprocess_exec(
            *cmd_args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=isolated_cwd,
            env=merged_env
        )

        return PrewarmedProcess(proc=proc, created_at=time.time(), model=model)

    def _ensure_gentle_fill_task(self, executable: Optional[str] = None, env: Optional[Dict[str, str]] = None):
        """确保后台单体温和补位任务正在运行"""
        if self._fill_task is None or self._fill_task.done():
            self._fill_task = asyncio.create_task(self._gentle_filler_loop(executable=executable, env=env))

    async def _gentle_filler_loop(self, executable: Optional[str] = None, env: Optional[Dict[str, str]] = None):
        """
        温和启动循环：
        逐个拉起待命进程，每个进程之间休眠 CLI_SPAWN_STAGGER_DELAY 秒 (默认 2 秒)，
        避免瞬间并发拉起 4 个 Node 进程导致 CPU 飙至 100% 打满机器。
        """
        while self._is_active:
            # 关键：每次拉起待命进程前主动让渡并错峰休眠，保证 CPU 曲线平稳
            try:
                await asyncio.sleep(ai_config.CLI_SPAWN_STAGGER_DELAY)
            except asyncio.CancelledError:
                break

            # 检查是否已达到设定的待命上限
            async with self._lock:
                current_standby = self._standby_queue.qsize()
                total_active = len(self._active_processes)
                if current_standby >= ai_config.CLI_STANDBY_POOL_SIZE:
                    break
                if current_standby + total_active >= ai_config.CLI_MAX_CONCURRENCY:
                    break

            try:
                worker = await self._spawn_worker(executable=executable, env=env)
                try:
                    self._standby_queue.put_nowait(worker)
                    logger.info(
                        f"[ProcessPool] 温和启动 1 个预热进程 (PID {worker.proc.pid}) 就绪，"
                        f"待命队列: {self._standby_queue.qsize()}/{ai_config.CLI_STANDBY_POOL_SIZE}"
                    )
                except asyncio.QueueFull:
                    await worker.terminate()
                    break
            except Exception as e:
                logger.error(f"[ProcessPool] 温和启动进程异常: {e}")
                break

    async def acquire_worker(
        self,
        executable: Optional[str] = None,
        model: Optional[str] = None,
        env: Optional[Dict[str, str]] = None
    ) -> PrewarmedProcess:
        """
        原子独占租借 Worker：
        1. 优先从已就绪待命队列秒级获取 (0ms 延迟，且模型匹配)；
        2. 若队列暂空或模型不匹配，在信号量控制下立即为当前请求拉起 1 个；
        3. 立即激活温和后台协程，以 2 秒间隔错峰补齐其余待命进程。
        """
        self._last_request_time = time.time()
        self._is_active = True

        worker: Optional[PrewarmedProcess] = None

        # 1. 尝试从待命队列原子取出与所请求 model 匹配且健康的进程
        mismatched: List[PrewarmedProcess] = []
        while not self._standby_queue.empty():
            try:
                candidate = self._standby_queue.get_nowait()
                if not candidate.is_alive:
                    await candidate.terminate()
                    continue
                cand_m = candidate.model or "gemini-3.8-flash"
                req_m = model or "gemini-3.8-flash"
                if cand_m == req_m:
                    worker = candidate
                    break
                else:
                    mismatched.append(candidate)
            except asyncio.QueueEmpty:
                break

        # 将未匹配但健康的待命进程放回待命队列
        for m in mismatched:
            try:
                self._standby_queue.put_nowait(m)
            except asyncio.QueueFull:
                await m.terminate()

        # 2. 队列无可用或无匹配模型，在信号量保护下立即拉起 1 个给当前请求专用
        if worker is None:
            async with self._semaphore:
                worker = await self._spawn_worker(executable=executable, model=model, env=env)

        worker.leased = True
        async with self._lock:
            self._active_processes.add(worker)

        # 3. 激活后台温和错峰补位
        self._ensure_gentle_fill_task(executable=executable, env=env)
        return worker

    async def release_worker(self, worker: PrewarmedProcess):
        """单次推演结束后用完即焚：彻底杀死进程，绝不复用"""
        async with self._lock:
            self._active_processes.discard(worker)
        await worker.terminate()

        # 归还后确保后台温和补齐待命数
        if self._is_active:
            self._ensure_gentle_fill_task()

# 全局单例
prewarmed_process_pool = PrewarmedProcessPool()
