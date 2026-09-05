import asyncio
import shlex
from typing import Optional, Callable, List, Any
from agent_core.tool import tool

# 危险指令过滤黑名单
DANGEROUS_COMMAND_SUBSTRINGS = [
    "rm -rf /",
    "rm -rf *",
    ":(){ :|:& };:",
    "mkfs",
    "dd if=",
    "> /dev/sda",
]

@tool(name="run_command", description="安全执行系统 Shell 命令行并获取标准输出与错误信息，支持流式日志推送与指定工作目录 (cwd)", category="shell")
async def run_command(
    command: str,
    cwd: Optional[str] = None,
    timeout: int = 60,
    on_progress: Optional[Callable[[str], Any]] = None
) -> str:
    """
    :param command: 待执行的终端命令字符串
    :param cwd: 可选的工作目录路径 (若留空则在默认环境根目录运行)
    :param timeout: 超时秒数 (默认 60 秒)
    """
    for blocked in DANGEROUS_COMMAND_SUBSTRINGS:
        if blocked in command:
            return f"Security Error: 命令包含高危危险指令 '{blocked}'，已被安全拦截！"

    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd
        )
        
        stdout_lines: List[str] = []
        stderr_lines: List[str] = []

        async def read_stream(stream, lines_list):
            if not stream:
                return
            while True:
                line_bytes = await stream.readline()
                if not line_bytes:
                    break
                line_str = line_bytes.decode("utf-8", errors="replace")
                lines_list.append(line_str)
                if on_progress:
                    try:
                        on_progress(line_str)
                    except Exception:
                        pass

        try:
            await asyncio.wait_for(
                asyncio.gather(
                    read_stream(proc.stdout, stdout_lines),
                    read_stream(proc.stderr, stderr_lines),
                    proc.wait()
                ),
                timeout=timeout
            )
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except Exception:
                pass
            return f"Timeout Error: 命令执行超过 {timeout} 秒限制被强制终止。"

        stdout = "".join(stdout_lines).strip()
        stderr = "".join(stderr_lines).strip()
        exit_code = proc.returncode

        output_parts = [f"Exit Code: {exit_code}"]
        if stdout:
            output_parts.append(f"STDOUT:\n{stdout}")
        if stderr:
            output_parts.append(f"STDERR:\n{stderr}")
        
        return "\n\n".join(output_parts)
    except Exception as e:
        return f"Execution Error: {str(e)}"
