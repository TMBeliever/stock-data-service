import os
import json
import time
import shutil
import asyncio
import logging
import glob
from typing import Optional, List, Dict, Set, Any, AsyncGenerator

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
    stream-json 双向通信预热进程：

    生命周期：
    1. spawn → 后台自动完成鉴权与 Google 远端握手
    2. stdout 输出 {"event":"init",...} → 标记 READY，放入待命队列
    3. 请求到达 → 原子独占领走 → stdin 写入 {"event":"user","message":{...}}
    4. 循环读取 stdout → {"event":"step_update","step_update":{"text_delta":"..."}}
    5. 收到 {"event":"result",...} → 本轮推演结束
    6. 用完即焚：terminate() 彻底杀死进程，绝不跨请求复用

    物理级管道隔离：独立进程独立匿名管道，并发绝不粘包、绝不串流。
    """

    def __init__(
        self,
        proc: asyncio.subprocess.Process,
        created_at: float,
        model: Optional[str] = None,
        effort: Optional[str] = None,
        conversation_id: Optional[str] = None,
    ):
        self.proc: asyncio.subprocess.Process = proc
        self.created_at: float = created_at
        self.model: Optional[str] = model
        self.effort: Optional[str] = effort
        self.conversation_id: Optional[str] = conversation_id
        self.leased: bool = False
        self._ready: bool = False  # 仅当收到 init 事件后为 True

    @property
    def is_alive(self) -> bool:
        return self.proc.returncode is None

    @property
    def is_ready(self) -> bool:
        return self._ready and self.is_alive

    async def wait_for_init(self, timeout: float = 30.0) -> bool:
        """
        阻塞等待子进程完成鉴权握手，直至 stdout 输出 {"event":"init",...}。
        返回 True 表示握手成功；超时或异常返回 False。
        """
        try:
            async def _read_init():
                if not self.proc.stdout:
                    return False
                while True:
                    raw = await self.proc.stdout.readline()
                    if not raw:
                        return False
                    line = raw.decode("utf-8", errors="replace").strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        # 非 JSON 行（如 stderr 混入或启动日志），跳过继续等待
                        logger.debug(f"[PrewarmedProcess] 握手期间忽略非JSON行: {line[:200]}")
                        continue
                    if data.get("event") == "init":
                        self.conversation_id = data.get("conversation_id")
                        init_info = data.get("init", {})
                        logger.info(
                            f"[PrewarmedProcess] ✅ 握手成功 (PID {self.proc.pid}, "
                            f"model={init_info.get('model', self.model)}, "
                            f"conversation={self.conversation_id})"
                        )
                        self._ready = True
                        return True

            return await asyncio.wait_for(_read_init(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.error(f"[PrewarmedProcess] ❌ 握手超时 ({timeout}s)，PID {self.proc.pid}")
            return False
        except Exception as e:
            logger.error(f"[PrewarmedProcess] ❌ 握手异常: {e}")
            return False

    async def execute_and_stream(self, prompt: str, timeout: float = 120.0) -> AsyncGenerator[StreamChunk, None]:
        """
        stream-json 双向通信：
        1. 向 stdin 写入 {"event":"user","message":{"content":"<prompt>"}} + 换行 (千万不要 close stdin！)
        2. 循环读取 stdout NDJSON，每次 readline 有独立超时保护：
           - event == "step_update" → 提取 text_delta 作为增量 Token
           - event == "result"     → 推演结束，yield finish_reason="stop"
        """
        if not self._ready or not self.is_alive:
            raise RuntimeError("[PrewarmedProcess] Worker 未就绪或已退出，无法执行推演")

        # 1. 写入 user 事件 (NDJSON 格式，严禁关闭 stdin)
        user_event = json.dumps(
            {"event": "user", "message": {"content": prompt}},
            ensure_ascii=False
        )
        try:
            if self.proc.stdin:
                self.proc.stdin.write((user_event + "\n").encode("utf-8"))
                await self.proc.stdin.drain()
        except Exception as e:
            logger.error(f"[PrewarmedProcess] 写入 stdin 异常: {e}")
            raise

        # 2. 循环读取 stdout 流式响应 (使用 deadline 模式而非包裹 wait_for)
        deadline = time.time() + timeout
        got_result = False

        if not self.proc.stdout:
            yield StreamChunk(finish_reason="stop")
            return

        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                logger.error(f"[PrewarmedProcess] 流式读取超时 ({timeout}s)")
                try:
                    self.proc.kill()
                except Exception:
                    pass
                raise TimeoutError(f"[PrewarmedProcess] 进程执行超时 (超限 {timeout}s)")

            try:
                raw = await asyncio.wait_for(
                    self.proc.stdout.readline(),
                    timeout=remaining
                )
            except asyncio.TimeoutError:
                logger.error(f"[PrewarmedProcess] 单行读取超时 (剩余预算耗尽)")
                try:
                    self.proc.kill()
                except Exception:
                    pass
                raise TimeoutError(f"[PrewarmedProcess] 进程执行超时 (超限 {timeout}s)")

            if not raw:
                # stdout EOF
                break

            line = raw.decode("utf-8", errors="replace").strip()
            if not line:
                continue

            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                # 非 JSON 行直接忽略
                continue

            event_type = data.get("event", "")

            if event_type == "step_update":
                step = data.get("step_update", {})
                text_delta = step.get("text_delta", "")
                if text_delta:
                    yield StreamChunk(delta=text_delta, role="assistant")

            elif event_type == "result":
                got_result = True
                result = data.get("result", {})
                yield StreamChunk(
                    finish_reason="stop",
                    raw_data=result
                )
                return

            # 其他事件类型暂时忽略

        if not got_result:
            # 进程 stdout 关闭但未收到 result 事件
            if not self.is_alive and self.proc.returncode != 0:
                stderr_bytes = await self.proc.stderr.read() if self.proc.stderr else b""
                err = stderr_bytes.decode("utf-8", errors="replace").strip()
                raise RuntimeError(
                    f"[PrewarmedProcess] 进程异常退出 ({self.proc.returncode}): {err}"
                )
            yield StreamChunk(finish_reason="stop")

    async def execute(self, prompt: str, timeout: float = 120.0) -> str:
        """非流式：等待完整推演并返回文本"""
        chunks: List[str] = []
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
                await asyncio.wait_for(self.proc.wait(), timeout=2.0)
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass


class PrewarmedProcessPool:
    """
    stream-json 双向通信预热待命进程池 (Pre-warmed Standby Process Pool)：

    核心架构升级：
    1. 真预热 (True Warmup)：拉起 agy 子进程后等待 {"event":"init"} 握手完成才入队，
       业务请求拿到的 Worker 已完成鉴权与模型加载，TTFT < 1s；
    2. NDJSON 管道通信：stdin/stdout 使用 stream-json 协议，每行一个 JSON 对象；
    3. 彻底无状态 (100% Stateless)：每个请求独占一次性进程，用完即焚；
    4. 物理级管道隔离：独立进程独立管道，并发绝不粘包、绝不串流；
    5. 温和错峰启动 (Gentle Warmup)：每个待命进程之间间隔 2 秒错峰拉起，杜绝 CPU 打满；
    6. 空闲归零 (Scale-to-Zero)：5 分钟内无请求自动释放所有进程。
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
        effort: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
        init_timeout: float = 30.0,
    ) -> PrewarmedProcess:
        """
        拉起一个 agy stream-json 子进程并等待 init 握手完成。
        只有握手成功的 Worker 才会返回，否则抛出异常。
        """
        from ai_core.providers.cli_provider import resolve_executable_path
        ensure_writable_gemini_environment()

        exe = resolve_executable_path(executable or ai_config.CLI_EXECUTABLE)

        effective_model = model or "gemini-3.8-flash"

        # 思考程度参数 (--effort) 处理：必须显式指定 low, medium, high
        target_effort = effort
        if not target_effort or str(target_effort).strip().lower() in ("", "off", "none"):
            target_effort = "medium"
        elif str(target_effort).strip().lower() not in ("low", "medium", "high"):
            target_effort = "medium"
        else:
            target_effort = str(target_effort).strip().lower()

        # 构造 stream-json 双向通信参数
        cmd_args = [
            exe,
            "--dangerously-skip-permissions",
            "--model", effective_model,
            "--effort", target_effort,
            "--input-format", "stream-json",
            "--output-format", "stream-json",
        ]

        # 部分版本支持 --disable-slash-commands
        cmd_args.append("--disable-slash-commands")

        # 运行在干净隔离的临时工作区目录
        isolated_cwd = "/tmp/quant_ai_clean_sandbox"
        os.makedirs(isolated_cwd, exist_ok=True)

        merged_env = os.environ.copy()
        if env:
            merged_env.update(env)
        merged_env["NO_COLOR"] = "1"
        merged_env["TERM"] = "dumb"
        if os.path.exists("/root/.gemini"):
            merged_env["GEMINI_CONFIG_DIR"] = "/root/.gemini"

        logger.info(
            f"[ProcessPool] 正在拉起 stream-json Worker: {' '.join(cmd_args[:6])}..."
        )

        proc = await asyncio.create_subprocess_exec(
            *cmd_args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=isolated_cwd,
            env=merged_env
        )

        worker = PrewarmedProcess(
            proc=proc,
            created_at=time.time(),
            model=effective_model,
            effort=target_effort
        )

        # 关键：等待 init 握手事件，只有握手成功才算就绪
        init_ok = await worker.wait_for_init(timeout=init_timeout)
        if not init_ok:
            # 握手失败，清理进程
            stderr_snippet = ""
            try:
                if proc.stderr:
                    stderr_bytes = await asyncio.wait_for(proc.stderr.read(2048), timeout=2.0)
                    stderr_snippet = stderr_bytes.decode("utf-8", errors="replace").strip()
            except Exception:
                pass
            await worker.terminate()
            raise RuntimeError(
                f"[ProcessPool] Worker 握手失败 (PID {proc.pid}, model={effective_model}): {stderr_snippet}"
            )

        return worker

    def _ensure_gentle_fill_task(
        self,
        executable: Optional[str] = None,
        model: Optional[str] = None,
        effort: Optional[str] = None,
        env: Optional[Dict[str, str]] = None
    ):
        """确保后台单体温和补位任务正在运行"""
        if self._fill_task is None or self._fill_task.done():
            self._fill_task = asyncio.create_task(
                self._gentle_filler_loop(executable=executable, model=model, effort=effort, env=env)
            )

    async def _gentle_filler_loop(
        self,
        executable: Optional[str] = None,
        model: Optional[str] = None,
        effort: Optional[str] = None,
        env: Optional[Dict[str, str]] = None
    ):
        """
        温和启动循环：
        逐个拉起待命进程并等待 init 握手完成，每个进程之间休眠 CLI_SPAWN_STAGGER_DELAY 秒，
        避免瞬间并发拉起导致 CPU 飙至 100% 打满机器。
        """
        target_m = model or "gemini-3.8-flash"
        target_e = effort or "medium"

        while self._is_active:
            # 错峰休眠
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
                worker = await self._spawn_worker(
                    executable=executable,
                    model=target_m,
                    effort=target_e,
                    env=env
                )
                try:
                    self._standby_queue.put_nowait(worker)
                    logger.info(
                        f"[ProcessPool] 温和启动 stream-json Worker 就绪 "
                        f"(PID {worker.proc.pid}, model={worker.model}, effort={worker.effort})，"
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
        effort: Optional[str] = None,
        env: Optional[Dict[str, str]] = None
    ) -> PrewarmedProcess:
        """
        原子独占租借 Worker：
        1. 优先从已就绪待命队列秒级获取 (0ms 延迟，且模型和思考深度匹配)；
        2. 若队列暂空或模型不匹配，在信号量控制下立即拉起 1 个并等待 init 握手；
        3. 立即激活温和后台协程，以 2 秒间隔错峰补齐其余待命进程。
        """
        self._last_request_time = time.time()
        self._is_active = True

        worker: Optional[PrewarmedProcess] = None
        req_m = model or "gemini-3.8-flash"
        req_e = effort or "medium"
        if str(req_e).strip().lower() in ("", "off", "none"):
            req_e = "medium"
        elif str(req_e).strip().lower() not in ("low", "medium", "high"):
            req_e = "medium"
        else:
            req_e = str(req_e).strip().lower()

        # 1. 尝试从待命队列原子取出与所请求 model & effort 匹配且健康就绪的进程
        mismatched: List[PrewarmedProcess] = []
        while not self._standby_queue.empty():
            try:
                candidate = self._standby_queue.get_nowait()
                if not candidate.is_ready:
                    await candidate.terminate()
                    continue
                cand_m = candidate.model or "gemini-3.8-flash"
                cand_e = candidate.effort or "medium"
                if cand_m == req_m and cand_e == req_e:
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
                worker = await self._spawn_worker(
                    executable=executable,
                    model=req_m,
                    effort=req_e,
                    env=env
                )

        worker.leased = True
        async with self._lock:
            self._active_processes.add(worker)

        logger.info(
            f"[ProcessPool] ⚡ Worker 已租出 (PID {worker.proc.pid}, "
            f"model={worker.model}, effort={worker.effort})"
        )

        # 3. 激活后台温和错峰补位
        self._ensure_gentle_fill_task(
            executable=executable,
            model=req_m,
            effort=req_e,
            env=env
        )
        return worker

    async def release_worker(self, worker: PrewarmedProcess):
        """单次推演结束后用完即焚：彻底杀死进程，绝不复用"""
        async with self._lock:
            self._active_processes.discard(worker)
        await worker.terminate()

        # 归还后确保后台温和补齐待命数
        if self._is_active:
            self._ensure_gentle_fill_task(
                model=worker.model,
                effort=worker.effort
            )


# 全局单例
prewarmed_process_pool = PrewarmedProcessPool()
