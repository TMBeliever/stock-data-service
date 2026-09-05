import os
from pathlib import Path
from typing import Optional
from agent_core.tool import tool

@tool(name="read_file", description="安全读取文件内容，支持起始行偏移 (offset) 与读取行数限制 (limit)", category="filesystem")
def read_file(path: str, offset: int = 1, limit: int = 200) -> str:
    """
    :param path: 文件绝对路径或相对工作区路径
    :param offset: 起始行号 (从 1 开始)
    :param limit: 最多读取行数 (默认 200)
    """
    file_path = Path(path)
    if not file_path.exists():
        return f"Error: 文件不存在 '{path}'"
    if not file_path.is_file():
        return f"Error: 目标路径不是有效文件 '{path}'"

    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()
        
        total = len(all_lines)
        start_idx = max(0, offset - 1)
        end_idx = min(total, start_idx + limit)
        slice_lines = all_lines[start_idx:end_idx]

        numbered_content = "".join(
            f"{i + start_idx + 1:4d} | {line}" for i, line in enumerate(slice_lines)
        )
        return (
            f"--- File: {path} (Lines {start_idx + 1}-{end_idx} of {total}) ---\n"
            f"{numbered_content}"
        )
    except Exception as e:
        return f"Error reading file '{path}': {str(e)}"

@tool(name="write_file", description="在指定路径创建或覆写文件内容", category="filesystem")
def write_file(path: str, content: str) -> str:
    """
    :param path: 文件路径
    :param content: 写入的完整文本
    """
    try:
        file_path = Path(path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Success: 已成功写入文件 '{path}' (共 {len(content)} 字符)"
    except Exception as e:
        return f"Error writing file '{path}': {str(e)}"

@tool(name="list_dir", description="列出指定目录下的文件与子目录清单", category="filesystem")
def list_dir(path: str = ".") -> str:
    """
    :param path: 目录路径，默认当前工作目录 '.'
    """
    dir_path = Path(path)
    if not dir_path.exists() or not dir_path.is_dir():
        return f"Error: 目标路径不是有效目录 '{path}'"

    try:
        items = os.listdir(dir_path)
        entries = []
        for it in sorted(items):
            full = dir_path / it
            kind = "[DIR] " if full.is_dir() else "[FILE]"
            entries.append(f"{kind} {it}")
        return f"Directory listing of '{path}' ({len(entries)} items):\n" + "\n".join(entries[:150])
    except Exception as e:
        return f"Error listing directory '{path}': {str(e)}"
