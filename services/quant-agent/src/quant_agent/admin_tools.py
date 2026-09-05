import os
import sys
import json
import shutil
import asyncio
import logging
import platform
import py_compile
from pathlib import Path
from typing import Optional, Dict, Any, List, Callable
import httpx

from agent_core.tool import tool, ToolRegistry, BaseTool
from agent_core.builtin_tools.shell import run_command
from quant_agent.config import agent_config

logger = logging.getLogger(__name__)

# 高危破坏性指令拦截黑名单 (杜绝清盘、清空文件系统、炸弹叉)
DESTRUCTIVE_COMMAND_BLACKLIST = [
    "rm -rf /",
    "rm -rf /*",
    ":(){ :|:& };:",
    "mkfs",
    "dd if=/dev/zero",
    "> /dev/sda",
    "> /dev/nvme",
    "fdisk /dev/",
    "chmod -R 777 /",
    "shutdown -h now",
    "reboot -f",
]

def map_host_path_to_container(path_str: str) -> str:
    """
    智能路径重映射：
    若当前处于 Docker 容器内部，宿主机的 /root 挂载在 /host_root，/home 挂载在 /host_home。
    自动将宿主机路径重映射为容器内真实可访问的有效路径。
    """
    if not path_str:
        return path_str

    clean_p = path_str.strip()
    if clean_p.startswith("/root") and Path("/host_root").exists():
        rel = clean_p[len("/root"):].lstrip("/\\")
        candidate = Path("/host_root") / rel if rel else Path("/host_root")
        if candidate.exists():
            return str(candidate)
    elif clean_p.startswith("/home") and Path("/host_home").exists():
        rel = clean_p[len("/home"):].lstrip("/\\")
        candidate = Path("/host_home") / rel if rel else Path("/host_home")
        if candidate.exists():
            return str(candidate)
    return clean_p

def _resolve_safe_path(rel_or_abs_path: str) -> Path:
    """校验并转换安全工作区路径，防止路径遍历穿越攻击，同时支持挂载工程与宿主机探测目录"""
    mapped = map_host_path_to_container(rel_or_abs_path)
    workspace = Path(agent_config.WORKSPACE_ROOT).resolve()
    target = Path(mapped)
    if not target.is_absolute():
        target = (workspace / target).resolve()
    else:
        target = target.resolve()

    # 安全目录白名单列表 (包括应用工作区、数据持久卷、宿主机挂载点)
    allowed_roots = [
        workspace,
        Path("/app/data").resolve() if Path("/app/data").exists() else None,
        Path("/host_home").resolve() if Path("/host_home").exists() else None,
        Path("/host_root").resolve() if Path("/host_root").exists() else None,
    ]
    allowed_roots = [r for r in allowed_roots if r is not None]

    is_safe = False
    for root in allowed_roots:
        try:
            target.relative_to(root)
            is_safe = True
            break
        except ValueError:
            continue

    if not is_safe:
        raise PermissionError(f"Access denied: Path '{rel_or_abs_path}' is outside permitted workspace roots")
    return target

# ==========================================
# 1. 系统资源与全微服务健康感知
# ==========================================

SERVICE_PORTS = {
    "stock-data": {"port": 8000, "probe": os.getenv("STOCK_DATA_PROBE_URL", f"{os.getenv('STOCK_DATA_API_URL', 'http://localhost:8000')}/docs")},
    "quant-agent": {"port": 8060, "probe": os.getenv("QUANT_AGENT_PROBE_URL", f"http://localhost:{agent_config.PORT}/health")},
    "ai-core": {"port": 8070, "probe": os.getenv("AI_CORE_PROBE_URL", f"{agent_config.AI_CORE_URL}/health")},
    "quant-server": {"port": 8080, "probe": os.getenv("QUANT_SERVER_PROBE_URL", f"{agent_config.QUANT_SERVER_URL}/health")},
    "common-server": {"port": 8090, "probe": os.getenv("COMMON_SERVER_PROBE_URL", f"{agent_config.COMMON_SERVER_URL}/health")},
    "web-admin": {"port": 5174, "probe": os.getenv("WEB_ADMIN_PROBE_URL", "http://localhost:5174/")},
}

@tool(
    name="admin_inspect_system_and_services",
    description="【超级管理员专属】全面体检服务器硬件资源 (CPU/内存/磁盘)、Docker 容器运行时与所有微服务运行健康状态",
    category="admin_devops"
)
async def admin_inspect_system_and_services() -> str:
    """全面体检服务器系统与微服务健康状态"""
    # 1. 操作系统信息
    uname = platform.uname()
    os_info = {
        "system": uname.system,
        "node": uname.node,
        "release": uname.release,
        "machine": uname.machine,
        "python_version": sys.version.split(" ")[0],
    }

    # 2. 磁盘空间
    disk = shutil.disk_usage(agent_config.WORKSPACE_ROOT)
    disk_info = {
        "total_gb": round(disk.total / (1024 ** 3), 2),
        "used_gb": round(disk.used / (1024 ** 3), 2),
        "free_gb": round(disk.free / (1024 ** 3), 2),
        "used_percent": f"{round((disk.used / disk.total) * 100, 1)}%"
    }

    # 3. 微服务探测
    service_status: Dict[str, Any] = {}
    async with httpx.AsyncClient(timeout=2.5) as client:
        for name, meta in SERVICE_PORTS.items():
            probe_url = meta["probe"]
            try:
                t0 = asyncio.get_event_loop().time()
                resp = await client.get(probe_url)
                cost_ms = round((asyncio.get_event_loop().time() - t0) * 1000, 1)
                is_ok = resp.status_code in (200, 307, 308)
                service_status[name] = {
                    "port": meta["port"],
                    "status": "ONLINE" if is_ok else f"HTTP_{resp.status_code}",
                    "latency_ms": cost_ms
                }
            except Exception as e:
                service_status[name] = {
                    "port": meta["port"],
                    "status": "OFFLINE",
                    "error": str(e).split(":")[-1].strip()
                }

    # 4. Docker 运行状态检查（捕获 stderr 以便 Agent 精确诊断失败原因，避免无效重试）
    docker_status = {"available": False, "running_containers": 0}
    try:
        proc = await asyncio.create_subprocess_shell(
            "docker ps -q",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=5.0)
        stdout_str = stdout.decode("utf-8", errors="replace").strip()
        stderr_str = stderr.decode("utf-8", errors="replace").strip()
        if proc.returncode == 0:
            lines = stdout_str.splitlines()
            docker_status = {
                "available": True,
                "running_containers": len([l for l in lines if l.strip()])
            }
        else:
            # 精确区分失败原因，帮助 Agent 直接给出结论
            reason = "未知原因"
            if "permission denied" in stderr_str.lower():
                reason = (
                    "权限拒绝 (permission denied): docker socket 权限不足。"
                    "修复方法: 在 docker-compose 中加 entrypoint chmod 666 /var/run/docker.sock，"
                    "或在宿主机执行 sudo chmod 666 /var/run/docker.sock"
                )
            elif "no such file" in stderr_str.lower() or "cannot connect" in stderr_str.lower():
                reason = "找不到 docker socket (no such file): /var/run/docker.sock 未挂载或宿主机 docker daemon 未运行"
            elif stderr_str:
                reason = stderr_str[:300]
            docker_status = {
                "available": False,
                "reason": reason,
                "raw_error": stderr_str[:200] if stderr_str else "exit_code=" + str(proc.returncode)
            }
    except Exception as e:
        docker_status = {"available": False, "reason": str(e)}


    report = {
        "os": os_info,
        "disk": disk_info,
        "services": service_status,
        "docker": docker_status
    }
    return json.dumps(report, ensure_ascii=False, indent=2)

# ==========================================
# 2. 源码安全阅读与智能编译修改
# ==========================================

@tool(
    name="admin_read_source_code",
    description="【超级管理员专属】安全读取项目源码文件，支持起始行偏移 (offset) 与读取行数限制 (limit)",
    category="admin_devops"
)
def admin_read_source_code(file_path: str, offset: int = 1, limit: int = 200) -> str:
    """
    :param file_path: 项目相对路径 (如 'services/quant-server/src/quant_server/main.py')
    :param offset: 起始行号 (默认 1)
    :param limit: 最多读取行数 (默认 200)
    """
    try:
        safe_path = _resolve_safe_path(file_path)
    except Exception as e:
        return f"Permission Error: {str(e)}"

    if not safe_path.exists():
        return f"Error: 文件不存在 '{file_path}'"
    if not safe_path.is_file():
        return f"Error: 目标路径不是有效文件 '{file_path}'"

    try:
        with open(safe_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()

        total = len(lines)
        start_idx = max(0, offset - 1)
        end_idx = min(total, start_idx + limit)
        slice_lines = lines[start_idx:end_idx]

        numbered = "".join(f"{i + start_idx + 1:4d} | {line}" for i, line in enumerate(slice_lines))
        return (
            f"--- [Admin Safe View] {file_path} (Lines {start_idx + 1}-{end_idx} of {total}) ---\n"
            f"{numbered}"
        )
    except Exception as e:
        return f"Error reading file '{file_path}': {str(e)}"

@tool(
    name="admin_modify_source_code",
    description="【超级管理员专属】修改或创建项目源码文件。内置自动语法预检 (py_compile/JSON 校验) 与失败即自动回滚防护，杜绝写坏文件导致系统故障！",
    category="admin_devops"
)
def admin_modify_source_code(file_path: str, content: str) -> str:
    """
    :param file_path: 项目相对路径 (如 'packages/agent-core/src/agent_core/tool.py')
    :param content: 写入或更新的代码完整文本
    """
    try:
        safe_path = _resolve_safe_path(file_path)
    except Exception as e:
        return f"Permission Error: {str(e)}"

    # 1. 备份原文件 (若存在)
    original_content: Optional[str] = None
    if safe_path.exists() and safe_path.is_file():
        with open(safe_path, "r", encoding="utf-8", errors="replace") as f:
            original_content = f.read()

    try:
        # 2. 写入新内容
        safe_path.parent.mkdir(parents=True, exist_ok=True)
        with open(safe_path, "w", encoding="utf-8") as f:
            f.write(content)

        # 3. 严格预检 (Pre-flight Syntax Verification)
        if safe_path.suffix == ".py":
            try:
                py_compile.compile(str(safe_path), doraise=True)
            except py_compile.PyCompileError as c_err:
                # 语法检查失败，触发自动回滚！
                if original_content is not None:
                    with open(safe_path, "w", encoding="utf-8") as f:
                        f.write(original_content)
                else:
                    safe_path.unlink(missing_ok=True)
                return f"Pre-flight Check Failed [Auto-Rolled Back]: Python 语法编译报错，修改已自动撤销！\n{c_err}"

        elif safe_path.suffix == ".json":
            try:
                json.loads(content)
            except Exception as j_err:
                if original_content is not None:
                    with open(safe_path, "w", encoding="utf-8") as f:
                        f.write(original_content)
                else:
                    safe_path.unlink(missing_ok=True)
                return f"Pre-flight Check Failed [Auto-Rolled Back]: JSON 解析失败，修改已自动撤销！\n{j_err}"

        line_count = len(content.splitlines())
        return f"Success: 文件 '{file_path}' 写入成功并已通过预编译语法检查！(共 {line_count} 行, {len(content)} 字符)"

    except Exception as e:
        # 意外异常回滚
        if original_content is not None:
            with open(safe_path, "w", encoding="utf-8") as f:
                f.write(original_content)
        return f"System Error during code modification: {str(e)}"

# ==========================================
# 3. 单元测试与质量验证
# ==========================================

@tool(
    name="admin_run_tests",
    description="【超级管理员专属】运行工作区单元测试 (pytest) 并输出测试覆盖与通过率，确保代码改动稳健可靠",
    category="admin_devops"
)
async def admin_run_tests(target: str = "packages/agent-core/tests", timeout: int = 45) -> str:
    """
    :param target: 测试目标目录或文件 (如 'packages/agent-core/tests', 'services/quant-agent/tests', 'packages/stock-data/tests')
    :param timeout: 超时时间秒数 (默认 45)
    """
    cmd = f"uv run pytest {target} -q --tb=short"
    try:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=agent_config.WORKSPACE_ROOT
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        out_text = stdout.decode("utf-8", errors="replace").strip()
        err_text = stderr.decode("utf-8", errors="replace").strip()
        exit_code = proc.returncode

        status_str = "PASSED" if exit_code == 0 else f"FAILED (Exit Code {exit_code})"
        res = [f"=== Test Execution Status: {status_str} ==="]
        if out_text:
            res.append(f"STDOUT:\n{out_text}")
        if err_text:
            res.append(f"STDERR:\n{err_text}")
        return "\n\n".join(res)
    except asyncio.TimeoutError:
        return f"Timeout Error: 测试运行超过 {timeout} 秒限制。"
    except Exception as e:
        return f"Execution Error: {str(e)}"

# ==========================================
# 4. 微服务热重载与生命周期管理
# ==========================================

@tool(
    name="admin_manage_service",
    description="【超级管理员专属】管理指定微服务生命周期：探测状态 (status)、优雅热重载/重启 (reload/restart) 或查看最近日志 (logs)",
    category="admin_devops"
)
async def admin_manage_service(service_name: str, action: str = "status") -> str:
    """
    :param service_name: 服务名称 ('stock-data', 'quant-agent', 'ai-core', 'quant-server', 'common-server', 'web-admin')
    :param action: 执行动作 ('status', 'reload', 'restart', 'logs')
    """
    if service_name not in SERVICE_PORTS:
        return f"Error: 未知服务名 '{service_name}'。支持列表: {list(SERVICE_PORTS.keys())}"

    meta = SERVICE_PORTS[service_name]
    port = meta["port"]
    probe_url = meta["probe"]

    if action == "status":
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(probe_url)
                return f"Service '{service_name}' (Port {port}): Status HTTP {resp.status_code}, Online."
        except Exception as e:
            return f"Service '{service_name}' (Port {port}): Offline or Unreachable ({str(e)})"

    elif action in ("reload", "restart"):
        # 在开发/热部署环境下，通过 touch 主入口文件触发 uvicorn 的自动 reload
        service_entrypoints = {
            "quant-agent": "services/quant-agent/src/quant_agent/main.py",
            "quant-server": "services/quant-server/src/quant_server/main.py",
            "common-server": "services/common-server/src/common_server/main.py",
            "ai-core": "packages/ai-core/src/ai_core/service.py",
            "stock-data": "packages/stock-data/main.py",
            "web-admin": "apps/web-admin/vite.config.ts",
        }
        rel_path = service_entrypoints.get(service_name)
        if rel_path:
            target_path = Path(agent_config.WORKSPACE_ROOT) / rel_path
            if target_path.exists():
                try:
                    os.utime(target_path, None)  # 更新时间戳触发热重载
                    await asyncio.sleep(1.0)
                    return f"Success: 已向 '{service_name}' 发送热重载信号 (Triggered file touch at {rel_path})。服务正在重新加载。"
                except Exception as e:
                    return f"Failed to trigger reload: {str(e)}"
        return f"Notice: 服务 '{service_name}' 未找到可触发的热重载入口文件。"

    elif action == "logs":
        # 尝试查找对应的最近输出或健康探针
        return f"Logs probe for '{service_name}': 端口 {port} 处于监听状态，如需查看详细系统日志，请通过 admin_execute_shell 查询日志文件或 systemd 服务状态。"

    return f"Error: 未知动作 '{action}'。支持: status, reload, restart, logs。"

# ==========================================
# 5. Docker 容器运行时与第三方基础设施治理
# ==========================================

@tool(
    name="admin_docker_manage",
    description="【超级管理员专属】管理 Ubuntu 服务器的 Docker 容器运行时与 Compose 服务 (支持 ps, images, pull, run, stop, restart, compose_up, compose_down)",
    category="admin_devops"
)
async def admin_docker_manage(action: str, args: str = "", on_progress: Optional[Callable[[str], Any]] = None) -> str:
    """
    :param action: 容器操作动作 ('ps', 'images', 'pull', 'run', 'stop', 'restart', 'compose_up', 'compose_down', 'compose_ps')
    :param args: 动作附加参数 (例如镜像名 'redis:alpine'、容器 ID 或 compose 文件参数)
    """
    action_map = {
        "ps": "docker ps -a",
        "images": "docker images",
        "pull": f"docker pull {args}",
        "run": f"docker run {args}",
        "start": f"docker start {args}",
        "stop": f"docker stop {args}",
        "restart": f"docker restart {args}",
        "logs": f"docker logs {args}",
        "exec": f"docker exec {args}",
        "compose_up": f"docker compose up -d {args}",
        "compose_down": f"docker compose down {args}",
        "compose_ps": f"docker compose ps {args}",
    }

    if action not in action_map:
        return f"Error: 不支持的 Docker 动作 '{action}'。支持列表: {list(action_map.keys())}"

    command = action_map[action].strip()

    # compose 类命令需在宿主机项目目录下运行（容器内无法找到 docker-compose.prod.yml）
    if action.startswith("compose"):
        host_root = os.getenv("HOST_PROJECT_ROOT", "").strip()
        mapped_host = map_host_path_to_container(host_root) if host_root else ""
        if mapped_host and Path(mapped_host).exists():
            command = f"cd {mapped_host} && {command}"
        elif host_root and host_root != agent_config.WORKSPACE_ROOT:
            # 切换到宿主机项目目录执行 compose 命令
            command = f"cd {host_root} && {command}"

    return await admin_execute_shell(command=command, timeout=120, on_progress=on_progress)

# ==========================================
# 6. Ubuntu 宿主机管理员 Shell 安全执行器
# ==========================================

@tool(
    name="admin_execute_shell",
    description="【超级管理员专属】在部署服务器或当前激活工程目录下执行系统运维 Shell 指令 (如 git status, git pull, uv sync, pnpm build, netstat 等)。支持传入 cwd 参数指定工程目录，内置宿主机路径自动重映射与破坏性指令拦截。",
    category="admin_devops"
)
async def admin_execute_shell(
    command: str,
    cwd: Optional[str] = None,
    timeout: int = 120,
    on_progress: Optional[Callable[[str], Any]] = None
) -> str:
    """
    :param command: 待执行的终端命令字符串
    :param cwd: 可选的工作目录绝对路径或相对路径 (若针对当前激活工程，请务必传入该工程路径)
    :param timeout: 超时秒数 (默认 120 秒)
    """
    cmd_lower = command.lower()
    for blocked in DESTRUCTIVE_COMMAND_BLACKLIST:
        if blocked in cmd_lower:
            return f"Security Intercepted: 命中灾难级系统破坏黑名单指令 '{blocked}'，已被安全熔断拦截！"

    # 解析与转换目标工作目录 (支持宿主机挂载路径映射)
    target_cwd = agent_config.WORKSPACE_ROOT
    if cwd and cwd.strip():
        mapped_cwd = map_host_path_to_container(cwd.strip())
        p = Path(mapped_cwd)
        if p.exists() and p.is_dir():
            target_cwd = str(p.resolve())
        else:
            logger.warning("Specified cwd '%s' (mapped: '%s') does not exist, falling back to %s", cwd, mapped_cwd, target_cwd)

    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=target_cwd
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
            return f"Timeout Error: 命令执行超过 {timeout} 秒限制被安全终止。"

        stdout = "".join(stdout_lines).strip()
        stderr = "".join(stderr_lines).strip()
        exit_code = proc.returncode

        output_parts = [
            f"=== Shell Exit Code: {exit_code} ===",
            f"Working Dir: {target_cwd}"
        ]
        if stdout:
            output_parts.append(f"STDOUT:\n{stdout}")
        if stderr:
            output_parts.append(f"STDERR:\n{stderr}")

        # 若为 Git 报错，附加针对性排查诊断，避免用户误解为缺少 git 命令
        if "fatal: not a git repository" in stderr.lower():
            output_parts.append(
                "💡 [诊断提示]: Git 执行报错：当前工作目录不是 Git 仓库（缺少 .git 目录）。\n"
                f"当前执行工作目录为: {target_cwd}\n"
                "• 若该工程为直接上传的代码压缩包或未初始化目录，请先在该目录下执行 `git init` 或在宿主机上通过 `git clone` 检出。\n"
                "• 若该工程是挂载的宿主机工程，请确认工作目录 cwd 是否正确指向了含有 .git 的实际工程根路径。"
            )
        elif "fatal: detected dubious ownership in repository" in stderr.lower():
            output_parts.append(
                "💡 [诊断提示]: Git 检测到目录属主不同（由于容器以 root 运行而宿主机文件为普通用户所有）。\n"
                f"可通过执行 `git config --global --add safe.directory {target_cwd}` 解除安全限制。"
            )
        elif "read-only file system" in stderr.lower():
            output_parts.append(
                "💡 [诊断提示]: 当前挂载目录为只读文件系统 (:ro)，Git 无法写入元数据或更新文件。请在 docker-compose 中调整挂载权限为读写。"
            )

        return "\n\n".join(output_parts)
    except Exception as e:
        return f"Shell Execution Error: {str(e)}"

# ==========================================
# 7. 超管工具注册表组装
# ==========================================

def get_admin_tool_registry() -> ToolRegistry:
    """组装并返回包含全套超级管理员运维工具的独立注册表"""
    registry = ToolRegistry()
    registry.register(admin_inspect_system_and_services)
    registry.register(admin_read_source_code)
    registry.register(admin_modify_source_code)
    registry.register(admin_run_tests)
    registry.register(admin_manage_service)
    registry.register(admin_docker_manage)
    registry.register(admin_execute_shell)
    registry.register(run_command)
    return registry
