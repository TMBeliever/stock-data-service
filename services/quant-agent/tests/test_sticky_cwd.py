import pytest
from pathlib import Path
from quant_agent.admin_tools import (
    admin_execute_shell,
    _resolve_safe_path,
    current_sticky_cwd,
    current_active_project_dir
)

@pytest.mark.asyncio
async def test_sticky_cwd_navigation(tmp_path):
    sub_dir = tmp_path / "subdir"
    sub_dir.mkdir()
    sample_file = sub_dir / "target.py"
    sample_file.write_text("print('hello world')")

    # 1. 初始未设置 sticky_cwd
    current_sticky_cwd.set(None)
    current_active_project_dir.set(str(tmp_path))

    # 2. 执行 cd 进入子目录
    res = await admin_execute_shell(command=f"cd {sub_dir} && ls")
    assert "Exit Code: 0" in res
    assert current_sticky_cwd.get() == str(sub_dir)

    # 3. 后续命令不传 cwd，自动继承 sticky_cwd
    res2 = await admin_execute_shell(command="ls")
    assert "target.py" in res2
    assert str(sub_dir) in res2

    # 4. _resolve_safe_path 优先在 sticky_cwd 下定位相对路径
    resolved = _resolve_safe_path("target.py")
    assert resolved == sample_file
