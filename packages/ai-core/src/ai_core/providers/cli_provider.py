import os
import re
import json
import uuid
import glob
import shutil
import asyncio
import logging
from typing import AsyncGenerator, List, Optional, Dict
from ai_core.base import BaseAIProvider
from ai_core.config import ai_config
from ai_core.models import Message, AIResponse, StreamChunk, ToolDefinition, ToolCall

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
    通过独占预热待命池调度原生 CLI (如 Google agy / gemini-cli)。
    彻底无状态 (Stateless)、用完即焚、零冷启动，杜绝任何工具拦截或会话串扰。
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

    def _format_messages_to_prompt(
        self,
        messages: List[Message],
        tools: Optional[List[ToolDefinition]] = None
    ) -> str:
        """将标准 Message 列表与可选工具声明渲染为适合 CLI 消费的纯文本提示词"""
        blocks: List[str] = []

        if tools:
            tool_schemas = [
                {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters
                }
                for t in tools
            ]
            blocks.append(
                "[SYSTEM_TOOLS_DEFINITIONS]\n"
                "You have access to the following tools. If you decide to call tools, respond with a JSON code block in this exact format:\n"
                "```json\n"
                "[\n"
                "  {\"tool_call\": {\"name\": \"tool_name\", \"arguments\": {\"arg1\": \"value1\"}}}\n"
                "]\n"
                "```\n"
                f"Available tools:\n{json.dumps(tool_schemas, ensure_ascii=False, indent=2)}\n"
            )

        if len(messages) == 1 and messages[0].role == "user" and messages[0].content and not tools:
            return messages[0].content

        for m in messages:
            role_tag = m.role.upper()
            content = m.content or ""
            if m.tool_calls:
                tc_data = [
                    {"name": tc.name, "arguments": tc.arguments}
                    for tc in m.tool_calls
                ]
                content = f"{content}\n[ASSISTANT_TOOL_CALLS]\n{json.dumps(tc_data, ensure_ascii=False)}"
            if m.tool_call_id:
                content = f"[TOOL_OUTPUT id={m.tool_call_id} name={m.name or ''}]\n{content}"
            blocks.append(f"[{role_tag}]\n{content}\n")
        return "\n".join(blocks).strip()

    def _parse_tool_calls_from_text(self, text: str) -> tuple[str, Optional[List[ToolCall]]]:
        """从 CLI 文本中提取 JSON 格式工具调用"""
        if not text:
            return text, None
        pattern = re.compile(r"```(?:json)?\s*([\[\{].*?[\]\}])\s*```", re.DOTALL)
        matches = pattern.findall(text)
        tool_calls: List[ToolCall] = []

        for raw_json in matches:
            try:
                parsed = json.loads(raw_json)
                items = parsed if isinstance(parsed, list) else [parsed]
                for item in items:
                    if isinstance(item, dict) and "tool_call" in item:
                        tc_info = item["tool_call"]
                        t_name = tc_info.get("name")
                        t_args = tc_info.get("arguments") or {}
                        if t_name:
                            tool_calls.append(ToolCall(
                                id=f"call_{uuid.uuid4().hex[:8]}",
                                name=t_name,
                                arguments=t_args,
                                raw_arguments=json.dumps(t_args, ensure_ascii=False)
                            ))
            except Exception:
                continue

        if tool_calls:
            return text, tool_calls
        return text, None

    def _build_command(
        self,
        prompt: str,
        model: Optional[str] = None
    ) -> tuple[List[str], bool]:
        """
        构建 argv 参数列表：
        返回 (cmd_args, needs_stdin_pipe)
        彻底无状态：严禁注入 --conversation / -c / --session-id / --resume
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
        if "gemini" in exe_lower:
            # gemini-cli: 使用 -y 开启无头非交互模式
            if "-y" not in cmd_args and "--yolo" not in cmd_args:
                cmd_args.append("-y")
            if model and "--model" not in cmd_args and "-m" not in cmd_args:
                cmd_args.extend(["--model", model])
        else:
            # Google agy 与 Claude CLI 均使用 --dangerously-skip-permissions (严禁传 -y 和 -m)
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

        # 认证目录环境配置：确保容器内 /root/.gemini 与 /root/.antigravity 具备真实读写能力
        try:
            from ai_core.process_pool import ensure_writable_gemini_environment
            ensure_writable_gemini_environment()
        except Exception:
            pass

        if os.path.exists("/root/.gemini"):
            env["GEMINI_CONFIG_DIR"] = "/root/.gemini"
        if os.path.exists("/root/.antigravity"):
            env["ANTIGRAVITY_CONFIG_DIR"] = "/root/.antigravity"

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
        """非流式调用 CLI 进程：优先从预热池获取就绪 Worker，用完即焚"""
        prompt = self._format_messages_to_prompt(messages, tools=tools)
        timeout = kwargs.get("timeout", self.timeout)
        resolved_exe = resolve_executable_path(self.executable)
        exe_lower = os.path.basename(resolved_exe).lower()

        # 针对默认 agy / gemini 走独占预热待命池，达到零冷启动
        if ("agy" in exe_lower or "gemini" in exe_lower) and not kwargs.get("args_template"):
            from ai_core.process_pool import prewarmed_process_pool
            worker = await prewarmed_process_pool.acquire_worker(
                executable=self.executable,
                model=kwargs.get("model"),
                env=self._get_env()
            )
            try:
                content_text = await worker.execute(prompt, timeout=timeout)
                clean_content, parsed_tools = self._parse_tool_calls_from_text(content_text)
                return AIResponse(
                    content=clean_content,
                    tool_calls=parsed_tools,
                    model=self.executable,
                    provider_type="cli",
                    finish_reason="tool_calls" if parsed_tools else "stop",
                    raw_response={"stdout": content_text}
                )
            finally:
                await prewarmed_process_pool.release_worker(worker)

        # 针对自定义 executable / 测试用例参数模板，走独立子进程
        cmd_args, needs_stdin = self._build_command(
            prompt,
            model=kwargs.get("model")
        )
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

        clean_content, parsed_tools = self._parse_tool_calls_from_text(stdout_text)
        return AIResponse(
            content=clean_content,
            tool_calls=parsed_tools,
            model=self.executable,
            provider_type="cli",
            finish_reason="tool_calls" if parsed_tools else "stop",
            raw_response={"stdout": stdout_text, "stderr": stderr_text, "returncode": proc.returncode}
        )

    async def generate_stream(
        self,
        messages: List[Message],
        tools: Optional[List[ToolDefinition]] = None,
        **kwargs
    ) -> AsyncGenerator[StreamChunk, None]:
        """流式调用 CLI 进程：优先从预热池获取就绪 Worker，用完即焚"""
        prompt = self._format_messages_to_prompt(messages, tools=tools)
        timeout = kwargs.get("timeout", self.timeout)
        resolved_exe = resolve_executable_path(self.executable)
        exe_lower = os.path.basename(resolved_exe).lower()

        # 针对默认 agy / gemini 走独占预热待命池，达到零冷启动
        if ("agy" in exe_lower or "gemini" in exe_lower) and not kwargs.get("args_template"):
            from ai_core.process_pool import prewarmed_process_pool
            worker = await prewarmed_process_pool.acquire_worker(
                executable=self.executable,
                model=kwargs.get("model"),
                env=self._get_env()
            )
            try:
                async for chunk in worker.execute_and_stream(prompt, timeout=timeout):
                    yield chunk
            finally:
                await prewarmed_process_pool.release_worker(worker)
            return

        # 针对自定义 executable / 测试用例参数模板，走独立子进程
        cmd_args, needs_stdin = self._build_command(
            prompt,
            model=kwargs.get("model")
        )
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
                line = await proc.stdout.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace")
                yield StreamChunk(delta=text, role="assistant")

        try:
            async for chunk in read_stream():
                yield chunk

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
