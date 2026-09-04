import os
import asyncio
import logging
from typing import AsyncGenerator, List, Optional, Dict
from ai_core.base import BaseAIProvider
from ai_core.config import ai_config
from ai_core.models import Message, AIResponse, StreamChunk, ToolDefinition

logger = logging.getLogger(__name__)

class CLIProcessProvider(BaseAIProvider):
    """
    安全异步命令行 (CLI) 驱动：
    通过操作系统异步子进程调度外部 CLI (如 Claude Code、Codex CLI、Aider、Ollama 等)。
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

    def _build_command(self, prompt: str) -> tuple[List[str], bool]:
        """
        构建 argv 参数列表：
        返回 (cmd_args, needs_stdin_pipe)
        若模板包含 {prompt}，则替换占位符直接作为命令行参数传参；
        否则通过标准输入 stdin 管道传给程序。
        """
        cmd_args: List[str] = [self.executable]
        has_prompt_placeholder = False

        for arg in self.args_template:
            if "{prompt}" in arg:
                cmd_args.append(arg.replace("{prompt}", prompt))
                has_prompt_placeholder = True
            else:
                cmd_args.append(arg)

        needs_stdin = not has_prompt_placeholder
        return cmd_args, needs_stdin

    def _get_env(self) -> Dict[str, str]:
        env = os.environ.copy()
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
        cmd_args, needs_stdin = self._build_command(prompt)
        timeout = kwargs.get("timeout", self.timeout)

        stdin_dest = asyncio.subprocess.PIPE if needs_stdin else None
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
        cmd_args, needs_stdin = self._build_command(prompt)
        timeout = kwargs.get("timeout", self.timeout)

        stdin_dest = asyncio.subprocess.PIPE if needs_stdin else None
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
