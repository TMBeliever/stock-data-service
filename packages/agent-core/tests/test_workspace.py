import tempfile
from pathlib import Path
from agent_core.workspace import WorkspaceManager

def test_workspace_manager_crud():
    with tempfile.TemporaryDirectory() as tmpdir:
        wm = WorkspaceManager(storage_dir=Path(tmpdir), workspace_root="/fake/root")
        
        # 1. 验证默认工程初始化
        projects = wm.list_projects()
        assert len(projects) >= 1
        assert any(p.name == "quant-system" for p in projects)
        
        # 2. 创建本地与部署机器上的项目
        p_remote = wm.create_project(
            name="payment-api",
            host_type="remote",
            path="/var/www/payment-api",
            machine_name="生产服务器01",
            machine_address="192.168.1.50",
            description="支付网关"
        )
        assert p_remote.id.startswith("proj_")
        assert p_remote.host_type == "remote"
        assert p_remote.machine_name == "生产服务器01"
        assert len(p_remote.sessions) == 1
        
        # 3. 创建会话与追加消息
        sess = wm.create_session(p_remote.id, title="排查支付回调慢")
        assert sess is not None
        assert sess.title == "排查支付回调慢"
        
        msg = wm.add_message_to_session(
            project_id=p_remote.id,
            session_id=sess.id,
            role="user",
            content="查看 Nginx access.log 慢请求",
            cards=[{"type": "code", "title": "Log Snippet", "content": "200 450ms"}]
        )
        assert msg is not None
        assert msg.content == "查看 Nginx access.log 慢请求"
        assert len(msg.cards) == 1
        
        # 4. 删除会话与删除项目
        assert wm.delete_session(p_remote.id, sess.id) is True
        assert wm.delete_project(p_remote.id) is True
        assert wm.get_project(p_remote.id) is None


def test_workspace_list_filesystem():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "folder_a").mkdir()
        (root / "folder_b").mkdir()
        (root / "folder_b" / "strategy.py").write_text("class MyStrategy: pass")
        (root / "file1.txt").write_text("hello")

        wm = WorkspaceManager(storage_dir=root / "storage", workspace_root=str(root))
        res = wm.list_filesystem_directory(target_path=str(root))

        assert res["current_path"] == str(root.resolve())
        assert len(res["items"]) >= 3
        # folder_b 应该被标记为 is_project
        proj_item = next((i for i in res["items"] if i["name"] == "folder_b"), None)
        assert proj_item is not None
        assert proj_item["is_dir"] is True
        assert proj_item["is_project"] is True


def test_workspace_import_uploaded_project():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        wm = WorkspaceManager(storage_dir=root / "storage", workspace_root=str(root))

        files_data = [
            ("main.py", b"print('alpha')"),
            ("strategies/dual_ma.py", b"class DualMa: pass")
        ]
        proj = wm.import_uploaded_project(
            project_name="my_uploaded_strategy",
            destination_dir=str(root / "uploaded"),
            host_type="remote",
            files_data=files_data
        )

        assert proj.name == "my_uploaded_strategy"
        assert proj.host_type == "remote"
        assert (Path(proj.path) / "main.py").exists()
        assert (Path(proj.path) / "strategies" / "dual_ma.py").exists()
        assert (Path(proj.path) / "strategies" / "dual_ma.py").read_text() == "class DualMa: pass"

