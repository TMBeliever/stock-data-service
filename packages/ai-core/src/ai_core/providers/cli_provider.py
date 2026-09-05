import os
import glob
import shutil
import asyncio
import logging
from typing import AsyncGenerator, List, Optional, Dict
from ai_core.base import BaseAIProvider
from ai_core.config import ai_config
from ai_core.models import Message, AIResponse, StreamChunk, ToolDefinition

logger = logging.getLogger(__name__)

def resolve_executable_path(executable: str) -> str:
    """
    智能解析 CLI 可执行程序完整路径：
    1. 优先检查系统当前 PATH；
    2. 检查是否为有效绝对路径；
    3. 在 Docker 容器环境中，智能探测宿主机挂载的可能路径 (/host_usr_local, /host_root 等)
    """
    if not executable:
        return executable

    # 1. PATH 中已存在
    which_path = shutil.which(executable)
    if which_path:
        return which_path

    # 2. 直接是已存在的文件
    if os.path.isabs(executable) and os.path.isfile(executable):
        return executable

    # 3. 容器中探测宿主机挂载路径
    exe_name = os.path.basename(executable)
    candidates = [
        f"/host_usr_local/bin/{exe_name}",
        f"/host_usr_local_bin/{exe_name}",
        f"/host_usr_bin/{exe_name}",
        f"/usr/local/bin/{exe_name}",
        f"/usr/bin/{exe_name}",
        f"/root/.local/bin/{exe_name}",
        f"/root/.antigravity/bin/{exe_name}",
        f"/host_root/.local/bin/{exe_name}",
        f"/host_root/.antigravity/bin/{exe_name}",
        f"/host_root/.cargo/bin/{exe_name}",
        f"/host_root/.npm-global/bin/{exe_name}",
    ]
    # 支持通配符搜寻 nvm / home 目录
    wildcard_patterns = [
        f"/host_root/.nvm/**/bin/{exe_name}",
        f"/host_home/*/.local/bin/{exe_name}",
        f"/host_home/*/.antigravity/bin/{exe_name}",
        f"/host_home/*/.nvm/**/bin/{exe_name}",
        f"/host_home/*/.cargo/bin/{exe_name}",
        f"/host_home/*/.npm-global/bin/{exe_name}",
    ]
    for p in candidates:
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p

    for wp in wildcard_patterns:
        matches = glob.glob(wp, recursive=True)
        for m in matches:
            if os.path.isfile(m) and os.access(m, os.X_OK):
                return m

    return executable

class CLIProcessProvider(BaseAIProvider):
    """
    安全异步命令行 (CLI) 驱动：
    通过操作系统异步子进程调度外部 CLI (如 Antigravity agy, Claude Code, Ollama 等)。
    严格使用参数数组 (argv) 传递，杜绝 shell=True 注入隐患，支持实时管道流式输出。
    """
    def __init__(
        self,
        executable: Optional[str] = None,
        args_template: Optional[List[str]] = None,
        timeout: Optional[float] = None,
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None
    ):
        self.executable = executable or ai_config.CLI_EXECUTABLE
        self.args_template = args_template or ai_config.CLI_ARGS
        self.timeout = timeout or ai_config.CLI_TIMEOUT
        self.cwd = cwd or ai_config.CLI_CWD
        self.env = env

    @property
    def provider_type(self) -> str:
        return "cli"

    def _format_messages_to_prompt(self, messages: List[Message]) -> str:
        """将标准 Message 列表渲染为适合 CLI 消费的提示文本"""
        if len(messages) == 1 and messages[0].role == "user" and messages[0].content:
            return messages[0].content

        blocks: List[str] = []
        for m in messages:
            role_tag = m.role.upper()
            content = m.content or ""
            blocks.append(f"[{role_tag}]\n{content}\n")
        return "\n".join(blocks).strip()

    def _build_command(self, prompt: str, model: Optional[str] = None) -> tuple[List[str], bool]:
        """
        构建 argv 参数列表：
        返回 (cmd_args, needs_stdin_pipe)
        自动解析可执行文件路径，若模板包含 {prompt}，则替换占位符直接作为命令行参数传参；
        否则通过标准输入 stdin 管道传给程序。
        """
        resolved_exe = resolve_executable_path(self.executable)
        cmd_args: List[str] = [resolved_exe]
        has_prompt_placeholder = False

        for arg in self.args_template:
            if "{prompt}" in arg:
                cmd_args.append(arg.replace("{prompt}", prompt))
                has_prompt_placeholder = True
            else:
                cmd_args.append(arg)

        # 针对不同 CLI 工具进行无头非交互模式安全自适应
        exe_lower = os.path.basename(resolved_exe).lower()
        if "agy" in exe_lower or "gemini" in exe_lower:
            # agy / gemini CLI: 保证带有 -y (YOLO 模式自动执行)，防止无头终端等待交互挂起
            if "-y" not in cmd_args and "--yolo" not in cmd_args and "--approval-mode" not in cmd_args:
                cmd_args.append("-y")
            if model and "-m" not in cmd_args and "--model" not in cmd_args:
                cmd_args.extend(["-m", model])
        elif "claude" in exe_lower:
            if "--dangerously-skip-permissions" not in cmd_args:
                cmd_args.append("--dangerously-skip-permissions")
            if model and "--model" not in cmd_args:
                cmd_args.extend(["--model", model])

        needs_stdin = not has_prompt_placeholder
        return cmd_args, needs_stdin

    def _get_env(self) -> Dict[str, str]:
        env = os.environ.copy()
        # 扩展 PATH 环境变量，确保可无缝访问宿主机挂载的 Node 与二进制工具
        extra_paths = [
            "/host_usr_local/bin",
            "/host_usr_local_bin",
            "/host_usr_bin",
            "/usr/local/bin",
            "/root/.local/bin",
            "/host_root/.local/bin",
            "/host_root/.antigravity/bin",
            "/host_root/.npm-global/bin",
        ]
        extra_paths += glob.glob("/host_root/.nvm/**/bin", recursive=True)
        extra_paths += glob.glob("/host_home/*/.nvm/**/bin", recursive=True)
        extra_paths += glob.glob("/host_home/*/.local/bin", recursive=True)

        valid_paths = [p for p in extra_paths if os.path.isdir(p)]
        if valid_paths:
            cur_path = env.get("PATH", "")
            env["PATH"] = ":".join(valid_paths) + ":" + cur_path

        # 认证目录配置补全与软链接映射：优先使用宿主机已认证的凭据
        if os.path.exists("/host_root/.gemini"):
            env["GEMINI_CONFIG_DIR"] = "/host_root/.gemini"
            if not os.path.exists("/root/.gemini"):
                try:
                    os.symlink("/host_root/.gemini", "/root/.gemini")
                except Exception:
                    pass
        elif not os.path.exists("/root/.gemini"):
            home_gemini = glob.glob("/host_home/*/.gemini")
            if home_gemini:
                env["GEMINI_CONFIG_DIR"] = home_gemini[0]
                try:
                    os.symlink(home_gemini[0], "/root/.gemini")
                except Exception:
                    pass

        if os.path.exists("/host_root/.antigravity"):
            env["ANTIGRAVITY_CONFIG_DIR"] = "/host_root/.antigravity"
            if not os.path.exists("/root/.antigravity"):
                try:
                    os.symlink("/host_root/.antigravity", "/root/.antigravity")
                except Exception:
                    pass
        elif not os.path.exists("/root/.antigravity"):
            home_ag = glob.glob("/host_home/*/.antigravity")
            if home_ag:
                env["ANTIGRAVITY_CONFIG_DIR"] = home_ag[0]
                try:
                    os.symlink(home_ag[0], "/root/.antigravity")
                except Exception:
                    pass

        # 强制禁用 ANSI 终端着色，保证流式文本纯净
        env["NO_COLOR"] = "1"
        if self.env:
            env.update(self.env)
        return env

    async def generate(
        self,
        messages: List[Message],
        tools: Optional[List[ToolDefinition]] = None,
        **kwargs
    ) -> AIResponse:
        """非流式调用 CLI 进程：等待进程执行完毕并捕获 stdout"""
        prompt = self._format_messages_to_prompt(messages)
        cmd_args, needs_stdin = self._build_command(prompt, model=kwargs.get("model"))
        timeout = kwargs.get("timeout", self.timeout)

        stdin_dest = asyncio.subprocess.PIPE if needs_stdin else asyncio.subprocess.DEVNULL
        proc = await asyncio.create_subprocess_exec(
            *cmd_args,
            stdin=stdin_dest,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self.cwd,
            env=self._get_env()
        )

        try:
            stdin_data = prompt.encode("utf-8") if needs_stdin else None
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(input=stdin_data),
                timeout=timeout
            )
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except Exception:
                pass
            raise TimeoutError(f"[CLIProcessProvider] 进程执行超时 (超限 {timeout}s): {cmd_args}")

        stdout_text = stdout_bytes.decode("utf-8", errors="replace").strip()
        stderr_text = stderr_bytes.decode("utf-8", errors="replace").strip()

        if proc.returncode != 0:
            raise RuntimeError(
                f"[CLIProcessProvider] 进程异常退出 (退出码 {proc.returncode}):\n{stderr_text or stdout_text}"
            )

        return AIResponse(
            content=stdout_text,
            model=self.executable,
            provider_type="cli",
            finish_reason="stop",
            raw_response={"stdout": stdout_text, "stderr": stderr_text, "returncode": proc.returncode}
        )

    async def generate_stream(
        self,
        messages: List[Message],
        tools: Optional[List[ToolDefinition]] = None,
        **kwargs
    ) -> AsyncGenerator[StreamChunk, None]:
        """流式调用 CLI 进程：逐块从 stdout 管道读取输出并 yield"""
        prompt = self._format_messages_to_prompt(messages)
        cmd_args, needs_stdin = self._build_command(prompt, model=kwargs.get("model"))
        timeout = kwargs.get("timeout", self.timeout)

        stdin_dest = asyncio.subprocess.PIPE if needs_stdin else asyncio.subprocess.DEVNULL
        proc = await asyncio.create_subprocess_exec(
            *cmd_args,
            stdin=stdin_dest,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self.cwd,
            env=self._get_env()
        )

        if needs_stdin and proc.stdin:
            proc.stdin.write(prompt.encode("utf-8"))
            await proc.stdin.drain()
            proc.stdin.close()

        async def read_stream():
            if not proc.stdout:
                return
            while True:
                # 按照块 (chunk) 或行读取，保障打字机实时体验
                line = await proc.stdout.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace")
                yield StreamChunk(delta=text, role="assistant")

        try:
            async for chunk in read_stream():
                yield chunk

            # 等待进程退出
            await asyncio.wait_for(proc.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except Exception:
                pass
            raise TimeoutError(f"[CLIProcessProvider] 进程执行超时 (超限 {timeout}s)")

        if proc.returncode != 0:
            stderr_bytes = await proc.stderr.read() if proc.stderr else b""
            err = stderr_bytes.decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"[CLIProcessProvider Stream] 进程异常退出 ({proc.returncode}): {err}")

        yield StreamChunk(finish_reason="stop")
