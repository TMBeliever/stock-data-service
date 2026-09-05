import json
import logging
import time
import uuid
from pathlib import Path
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

class SessionMessage(BaseModel):
    id: str = Field(default_factory=lambda: f"msg_{uuid.uuid4().hex[:8]}")
    role: str  # 'user' | 'assistant' | 'system'
    content: str
    timestamp: float = Field(default_factory=time.time)
    cards: Optional[List[Dict[str, Any]]] = None  # 类似 Codex 原图的 </> 纯文本/代码卡片
    tool_calls: Optional[List[Dict[str, Any]]] = None

class ProjectSession(BaseModel):
    id: str = Field(default_factory=lambda: f"sess_{uuid.uuid4().hex[:8]}")
    project_id: str
    title: str = "新对话"
    last_snippet: str = ""
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
    messages: List[SessionMessage] = Field(default_factory=list)

class Project(BaseModel):
    id: str = Field(default_factory=lambda: f"proj_{uuid.uuid4().hex[:8]}")
    name: str
    host_type: str = "local"  # 'local' | 'remote'
    machine_name: str = "本机环境"
    machine_address: Optional[str] = "127.0.0.1"
    path: str
    description: str = ""
    created_at: float = Field(default_factory=time.time)
    sessions: List[ProjectSession] = Field(default_factory=list)

def get_default_preset_projects(workspace_root: str = ".") -> List[Project]:
    """生成内置的高保真默认项目与任务会话结构 (对齐 Codex 交互视图)"""
    proj_main = Project(
        id="proj_quant_system",
        name="quant-system",
        host_type="local",
        machine_name="本机开发机 (macOS)",
        machine_address="127.0.0.1",
        path=str(workspace_root),
        description="A 股全生命周期量化回测与实盘投研中台",
        sessions=[
            ProjectSession(
                id="sess_arch_eval",
                project_id="proj_quant_system",
                title="评估项目架构合理性",
                last_snippet="但它不适合作为你项目唯一的交易内核，尤其是 A 股 T+1 交易规则...",
                messages=[
                    SessionMessage(
                        role="user",
                        content="帮我分析一下，这个项目架构合理吗？是否适合直接使用 VectorBT 作为核心交易引擎？",
                        timestamp=time.time() - 3600
                    ),
                    SessionMessage(
                        role="assistant",
                        content="""但它不适合作为你项目唯一的交易内核，尤其是：
- **A 股 T+1 制度约束**
- **当日买入不可卖出**
- **涨跌停与停牌撮合保护**
- **整手交易规则 (100股)**
- **Next-Open 真实撮合成交**

所以在你的项目里，我建议在 `quant-core` 中自研撮合内核，并提供标准策略基类：

```python
from quant_core.strategy import BaseStrategy, Signal

class DualMaStrategy(BaseStrategy):
    def __init__(self, fast_period: int = 5, slow_period: int = 20):
        super().__init__()
        self.fast = fast_period
        self.slow = slow_period

    def on_bar(self, bar):
        fast_ma = self.sma(self.fast)
        slow_ma = self.sma(self.slow)
        if fast_ma > slow_ma and not self.has_position:
            return Signal.buy(bar.symbol, amount=100)
        elif fast_ma < slow_ma and self.has_position:
            return Signal.sell(bar.symbol, amount=100)
        return Signal.hold()
```

如上所示，结合事件驱动与 T+1 约束，策略回测具备实盘级严谨度。""",
                        cards=[
                            {
                                "type": "code",
                                "title": "DualMaStrategy.py",
                                "language": "python",
                                "content": "class DualMaStrategy(BaseStrategy):\n    def on_bar(self, bar):\n        if self.sma(5) > self.sma(20):\n            return Signal.buy(bar.symbol, 100)\n        return Signal.hold()"
                            }
                        ],
                        tool_calls=[
                            {
                                "id": "tc_validate_code_1",
                                "name": "validate_strategy_code",
                                "arguments": {"strategy_name": "DualMaStrategy", "strict_t1": True},
                                "status": "done",
                                "step": 1,
                                "output_preview": "{\"status\":\"success\",\"message\":\"AST 语法树校验通过，无未来函数，严格遵循 A 股 T+1 撮合约束\"}"
                            }
                        ],
                        timestamp=time.time() - 3550
                    )
                ]
            ),
            ProjectSession(
                id="sess_quant_analysis",
                project_id="proj_quant_system",
                title="帮我分析一下，这个项目架构合理",
                last_snippet="微服务分层清晰，common-server负责用户，quant-agent负责智能推理...",
                messages=[]
            )
        ]
    )

    return [proj_main]


class WorkspaceManager:
    """通用智能体多项目工程与会话工作空间管理器 (agent-core 通用能力)"""

    def __init__(self, storage_dir: Optional[Path] = None, workspace_root: str = "."):
        self.storage_dir = storage_dir or (Path.home() / ".agent_workspace")
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.workspace_root = workspace_root
        self._file = self.storage_dir / "projects.json"
        self._projects: Dict[str, Project] = {}
        self._load()

    def _load(self):
        if not self._file.exists():
            defaults = get_default_preset_projects(self.workspace_root)
            self._projects = {p.id: p for p in defaults}
            self._save()
            return

        try:
            with open(self._file, "r", encoding="utf-8") as f:
                data = json.load(f)
                self._projects = {
                    item["id"]: Project.model_validate(item)
                    for item in data.get("projects", [])
                }
        except Exception as e:
            logger.error("Failed to load workspace projects: %s", e)
            defaults = get_default_preset_projects(self.workspace_root)
            self._projects = {p.id: p for p in defaults}
            self._save()

    def _save(self):
        try:
            data = {
                "updated_at": time.time(),
                "projects": [p.model_dump() for p in self._projects.values()]
            }
            with open(self._file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error("Failed to save workspace projects: %s", e)

    def list_projects(self) -> List[Project]:
        self._load()
        return list(self._projects.values())


    def get_project(self, project_id: str) -> Optional[Project]:
        return self._projects.get(project_id)

    def create_project(
        self,
        name: str,
        host_type: str,
        path: str,
        machine_name: str = "",
        machine_address: str = "",
        description: str = ""
    ) -> Project:
        proj_id = f"proj_{uuid.uuid4().hex[:8]}"
        m_name = machine_name or ("本机环境" if host_type == "local" else "部署服务器节点")
        new_proj = Project(
            id=proj_id,
            name=name.strip(),
            host_type=host_type,
            machine_name=m_name,
            machine_address=machine_address.strip() or ("127.0.0.1" if host_type == "local" else ""),
            path=path.strip(),
            description=description.strip(),
            sessions=[
                ProjectSession(
                    project_id=proj_id,
                    title="新对话",
                    last_snippet="欢迎使用 Codex 工作台，请输入您的问题开始！"
                )
            ]
        )
        self._projects[proj_id] = new_proj
        self._save()
        return new_proj

    def delete_project(self, project_id: str) -> bool:
        if project_id in self._projects:
            del self._projects[project_id]
            self._save()
            return True
        return False

    def create_session(self, project_id: str, title: str = "新对话") -> Optional[ProjectSession]:
        proj = self._projects.get(project_id)
        if not proj:
            return None
        sess = ProjectSession(
            project_id=project_id,
            title=title.strip() or "新对话",
            last_snippet=""
        )
        proj.sessions.insert(0, sess)
        self._save()
        return sess

    def get_session(self, project_id: str, session_id: str) -> Optional[ProjectSession]:
        proj = self._projects.get(project_id)
        if not proj:
            return None
        for s in proj.sessions:
            if s.id == session_id:
                return s
        return None

    def add_message_to_session(
        self,
        project_id: str,
        session_id: str,
        role: str,
        content: str,
        cards: Optional[List[Dict[str, Any]]] = None,
        tool_calls: Optional[List[Dict[str, Any]]] = None,
        message_id: Optional[str] = None
    ) -> Optional[SessionMessage]:
        sess = self.get_session(project_id, session_id)
        if not sess:
            return None

        # 若指定了 message_id，查找是否已有旧记录在会话中（如流式增量/审批推进更新），就地覆盖更新
        if message_id:
            for existing in sess.messages:
                if existing.id == message_id:
                    existing.content = content
                    existing.cards = cards
                    existing.tool_calls = tool_calls
                    existing.timestamp = time.time()
                    sess.updated_at = time.time()
                    if content:
                        sess.last_snippet = content[:80]
                    self._save()
                    return existing

        msg = SessionMessage(
            id=message_id or f"msg_{uuid.uuid4().hex[:8]}",
            role=role,
            content=content,
            cards=cards,
            tool_calls=tool_calls,
            timestamp=time.time()
        )
        sess.messages.append(msg)
        sess.updated_at = time.time()
        sess.last_snippet = content[:80] if content else ""
        if len(sess.messages) == 1 and role == "user":
            sess.title = content[:20] if len(content) <= 20 else content[:18] + "..."
        self._save()
        return msg

    def delete_session(self, project_id: str, session_id: str) -> bool:
        proj = self._projects.get(project_id)
        if not proj:
            return False
        orig_len = len(proj.sessions)
        proj.sessions = [s for s in proj.sessions if s.id != session_id]
        if len(proj.sessions) < orig_len:
            self._save()
            return True
        return False

    def list_filesystem_directory(
        self,
        target_path: Optional[str] = None,
        show_hidden: bool = False
    ) -> Dict[str, Any]:
        """浏览服务端/部署机上的文件目录树 (支持方案 A 远程挂载)"""
        import platform
        import shutil

        # 确定目标目录，未指定时默认从 workspace_root 或 Home 展开
        if not target_path or target_path.strip() in ("", "~"):
            base_dir = Path.home()
        else:
            base_dir = Path(target_path).expanduser()

        try:
            resolved_path = base_dir.resolve()
        except Exception:
            resolved_path = Path.home()

        if not resolved_path.exists() or not resolved_path.is_dir():
            resolved_path = Path.home()

        current_path_str = str(resolved_path)
        parent_path_str = str(resolved_path.parent) if resolved_path != resolved_path.parent else None

        # 面包屑导航片段
        breadcrumbs = []
        parts = resolved_path.parts
        if parts:
            curr_accum = Path(parts[0])
            breadcrumbs.append({"name": str(curr_accum), "path": str(curr_accum)})
            for part in parts[1:]:
                curr_accum = curr_accum / part
                breadcrumbs.append({"name": part, "path": str(curr_accum)})

        # 快捷常用入口
        quick_roots = [
            {"name": "当前量化根目录", "path": str(Path(self.workspace_root).resolve()), "icon": "⚡"},
            {"name": "用户主目录 (~)", "path": str(Path.home()), "icon": "🏠"},
            {"name": "系统根目录 (/)", "path": "/", "icon": "🖥️"},
        ]
        if Path("/host_home").exists():
            quick_roots.append({"name": "宿主机用户目录 (/host_home)", "path": "/host_home", "icon": "🖥️"})
        if Path("/data").exists():
            quick_roots.append({"name": "数据目录 (/data)", "path": "/data", "icon": "💾"})

        items = []
        try:
            for entry in resolved_path.iterdir():
                if not show_hidden and entry.name.startswith("."):
                    continue

                is_directory = entry.is_dir()
                is_proj = False
                has_children = False

                if is_directory:
                    try:
                        project_indicators = [
                            "pyproject.toml", "requirements.txt", "setup.py",
                            "package.json", "main.py", ".git", "strategies", "strategy.py"
                        ]
                        for ind in project_indicators:
                            if (entry / ind).exists():
                                is_proj = True
                                break
                        for sub in entry.iterdir():
                            if show_hidden or not sub.name.startswith("."):
                                has_children = True
                                break
                    except (PermissionError, OSError):
                        pass

                size_bytes = 0
                updated_at = 0.0
                try:
                    stat = entry.stat()
                    size_bytes = stat.st_size
                    updated_at = stat.st_mtime
                except Exception:
                    pass

                items.append({
                    "name": entry.name,
                    "path": str(entry),
                    "is_dir": is_directory,
                    "is_project": is_proj,
                    "has_children": has_children,
                    "size": size_bytes,
                    "updated_at": updated_at
                })
        except PermissionError:
            pass
        except Exception as e:
            logger.warning("Error reading directory %s: %s", resolved_path, e)

        # 排序：文件夹优先（字母序），文件其次
        items.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))

        free_gb = 0.0
        try:
            usage = shutil.disk_usage(resolved_path)
            free_gb = round(usage.free / (1024 ** 3), 1)
        except Exception:
            pass

        return {
            "current_path": current_path_str,
            "parent_path": parent_path_str,
            "breadcrumbs": breadcrumbs,
            "quick_roots": quick_roots,
            "items": items,
            "total_items": len(items),
            "free_space_gb": free_gb,
            "system_info": {
                "os": platform.system(),
                "node": platform.node(),
                "release": platform.release(),
                "machine": platform.machine()
            }
        }

    def import_uploaded_project(
        self,
        project_name: str,
        destination_dir: Optional[str] = None,
        host_type: str = "remote",
        machine_name: str = "",
        files_data: Optional[List[tuple[str, bytes]]] = None,
        zip_bytes: Optional[bytes] = None,
    ) -> Project:
        """接收访问机客户端上传的项目文件/压缩包，保存到部署服务器并注册挂载工程"""
        import io
        import zipfile

        clean_name = project_name.strip() or f"uploaded_project_{int(time.time())}"

        if destination_dir and destination_dir.strip():
            dest_root = Path(destination_dir.strip()).expanduser().resolve()
        else:
            dest_root = (self.storage_dir / "uploaded_projects").resolve()

        project_path = dest_root / clean_name
        project_path.mkdir(parents=True, exist_ok=True)

        if zip_bytes:
            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
                zf.extractall(project_path)

        if files_data:
            for rel_path, content in files_data:
                safe_rel = rel_path.lstrip("/\\")
                if ".." in safe_rel.split("/") or ".." in safe_rel.split("\\"):
                    continue
                file_dest = project_path / safe_rel
                file_dest.parent.mkdir(parents=True, exist_ok=True)
                file_dest.write_bytes(content)

        m_name = machine_name or ("当前部署机节点 (Ubuntu/Linux)" if host_type == "remote" else "本机环境")
        new_project = self.create_project(
            name=clean_name,
            host_type=host_type,
            path=str(project_path),
            machine_name=m_name,
            description=f"从访问机上传的量化策略工程 (已挂载于部署机: {project_path})"
        )
        return new_project

    def discover_projects_on_system(self) -> List[Dict[str, Any]]:
        """在部署机/服务端全自动探测可用的量化与代码工程 (无需用户知晓或手输路径)"""
        discovered = []
        scanned_paths = set()
        self._load()
        mounted_paths = {p.path for p in self._projects.values()}

        # 扫描候选根目录
        candidate_roots = []
        try:
            ws_root = Path(self.workspace_root).resolve()
            candidate_roots.append(ws_root)
            if ws_root.parent and ws_root.parent != ws_root:
                candidate_roots.append(ws_root.parent)
        except Exception:
            pass

        try:
            home = Path.home().resolve()
            candidate_roots.append(home)
            for sub_name in ["projects", "workspace", "code", "quant", "strategies", "Desktop", "Documents"]:
                sub_dir = home / sub_name
                if sub_dir.exists() and sub_dir.is_dir():
                    candidate_roots.append(sub_dir)
        except Exception:
            pass

        for sys_path in ["/host_home", "/data", "/data/projects", "/opt/projects", "/var/www"]:
            p = Path(sys_path)
            if p.exists() and p.is_dir():
                candidate_roots.append(p)

        def inspect_and_add(candidate: Path, depth: int = 0):
            if str(candidate) in scanned_paths or depth > 2:
                return
            scanned_paths.add(str(candidate))

            if not candidate.exists() or not candidate.is_dir():
                return

            if candidate.name.startswith(".") or candidate.name in ("node_modules", ".venv", "venv", "__pycache__", "dist", "build", "AppData", "Library"):
                return

            is_proj = False
            tags = []
            desc = ""

            indicators = {
                "strategy.py": ("Python 策略工程", "⚡ 量化策略"),
                "pyproject.toml": ("Python 现代工程", "🐍 Python"),
                "requirements.txt": ("Python 依赖工程", "🐍 Python"),
                "package.json": ("前端/Node 交互工程", "🌐 Web"),
                "main.py": ("Python 核心应用", "🚀 Python"),
                ".git": ("Git 版本库", "📦 Git"),
            }

            for ind_file, (tag_label, badge_name) in indicators.items():
                if (candidate / ind_file).exists():
                    is_proj = True
                    if badge_name not in tags:
                        tags.append(badge_name)
                    if not desc:
                        desc = tag_label

            if is_proj:
                try:
                    stat = candidate.stat()
                    mtime = stat.st_mtime
                except Exception:
                    mtime = 0.0

                discovered.append({
                    "name": candidate.name,
                    "path": str(candidate),
                    "tags": tags,
                    "description": desc or "代码工程目录",
                    "updated_at": mtime,
                    "is_mounted": str(candidate) in mounted_paths,
                    "is_current": str(candidate) == str(Path(self.workspace_root).resolve()),
                })
                # 命中顶层工程后停止向下深挖，保持工程列表干净纯粹
                return

            try:
                for sub in candidate.iterdir():
                    if sub.is_dir() and not sub.name.startswith("."):
                        inspect_and_add(sub, depth + 1)
            except (PermissionError, OSError):
                pass

        for root in candidate_roots:
            try:
                if root.exists() and root.is_dir():
                    for sub in root.iterdir():
                        if sub.is_dir():
                            inspect_and_add(sub, depth=0)
            except (PermissionError, OSError):
                pass

        # 排序：当前正在运行的优先，未挂载的优先，更新时间最新的优先
        discovered.sort(key=lambda x: (
            not x["is_current"],
            x["is_mounted"],
            -x["updated_at"]
        ))

        unique_results = []
        seen = set()
        for item in discovered:
            if item["path"] not in seen:
                seen.add(item["path"])
                unique_results.append(item)

        return unique_results

