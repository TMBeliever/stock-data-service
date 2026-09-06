import sys
import pytest
from ai_core.providers.cli_provider import CLIProcessProvider
from ai_core.models import Message

@pytest.mark.asyncio
async def test_cli_provider_with_placeholder():
    """测试通过命令行参数占位符 {prompt} 传参的 CLI 驱动"""
    provider = CLIProcessProvider(
        executable=sys.executable,
        args_template=["-c", "import sys; print('RESULT: ' + sys.argv[1])", "{prompt}"]
    )

    messages = [Message.user("QuantStrategy101")]
    res = await provider.generate(messages)

    assert res.provider_type == "cli"
    assert "RESULT: QuantStrategy101" in res.content

@pytest.mark.asyncio
async def test_cli_provider_with_stdin_pipe():
    """测试通过标准输入 stdin 管道传参的 CLI 驱动"""
    provider = CLIProcessProvider(
        executable=sys.executable,
        args_template=["-c", "import sys; print('STDIN_GOT: ' + sys.stdin.read().strip())"]
    )

    messages = [Message.user("DCA_BACKTEST_PROMPT")]
    res = await provider.generate(messages)

    assert res.provider_type == "cli"
    assert "STDIN_GOT: DCA_BACKTEST_PROMPT" in res.content

@pytest.mark.asyncio
async def test_cli_provider_streaming():
    """测试 CLI 驱动的实时管道逐行流式读取"""
    code = (
        "import sys, time\n"
        "for i in [1, 2, 3]:\n"
        "    print(f'LINE_{i}', flush=True)\n"
    )
    provider = CLIProcessProvider(
        executable=sys.executable,
        args_template=["-c", code]
    )

    chunks = []
    async for chunk in provider.generate_stream([Message.user("start")]):
        if chunk.delta:
            chunks.append(chunk.delta)

    full_output = "".join(chunks)
    assert "LINE_1" in full_output
    assert "LINE_2" in full_output
    assert "LINE_3" in full_output

@pytest.mark.asyncio
async def test_cli_provider_timeout():
    """测试 CLI 进程超限超时安全清理"""
    provider = CLIProcessProvider(
        executable=sys.executable,
        args_template=["-c", "import time; time.sleep(5)"],
        timeout=0.3
    )

    with pytest.raises(TimeoutError):
        await provider.generate([Message.user("sleep")])

def test_cli_provider_flag_adaptation():
    """测试不同 CLI 可执行文件的参数自适应：agy 必须使用 --dangerously-skip-permissions 和 --model，严禁传 -y 和 -m"""
    # 1. agy
    p_agy = CLIProcessProvider(executable="agy", args_template=["-p", "{prompt}"])
    cmd_agy, _ = p_agy._build_command("hello", model="claude-sonnet-4.6")
    assert "--dangerously-skip-permissions" in cmd_agy
    assert "--model" in cmd_agy
    assert "claude-sonnet-4.6" in cmd_agy
    assert "-y" not in cmd_agy
    assert "-m" not in cmd_agy

    # 2. gemini
    p_gem = CLIProcessProvider(executable="gemini", args_template=["-p", "{prompt}"])
    cmd_gem, _ = p_gem._build_command("hello", model="gemini-3.8-flash")
    assert "-y" in cmd_gem
    assert "--model" in cmd_gem
    assert "--dangerously-skip-permissions" not in cmd_gem

    # 3. claude
    p_claude = CLIProcessProvider(executable="claude", args_template=["-p", "{prompt}"])
    cmd_claude, _ = p_claude._build_command("hello", model="claude-3-5-sonnet")
    assert "--dangerously-skip-permissions" in cmd_claude
    assert "--model" in cmd_claude

