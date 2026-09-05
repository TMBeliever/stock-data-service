import asyncio
import shlex
from typing import Optional
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

@tool(name="run_command", description="安全执行系统 Shell 命令行并获取标准输出与错误信息", category="shell")
async def run_command(command: str, timeout: int = 30) -> str:
    """
    :param command: 待执行的终端命令字符串
    :param timeout: 超时秒数 (默认 30 秒)
    """
    for blocked in DANGEROUS_COMMAND_SUBSTRINGS:
        if blocked in command:
            return f"Security Error: 命令包含高危危险指令 '{blocked}'，已被安全拦截！"

    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except Exception:
                pass
            return f"Timeout Error: 命令执行超过 {timeout} 秒限制被强制终止。"

        stdout = stdout_bytes.decode("utf-8", errors="replace").strip()
        stderr = stderr_bytes.decode("utf-8", errors="replace").strip()
        exit_code = proc.returncode

        output_parts = [f"Exit Code: {exit_code}"]
        if stdout:
            output_parts.append(f"STDOUT:\n{stdout}")
        if stderr:
            output_parts.append(f"STDERR:\n{stderr}")
        
        return "\n\n".join(output_parts)
    except Exception as e:
        return f"Execution Error: {str(e)}"
