from agent_core.guards import RepeatToolGuard, GuardAlert

def test_canonicalize_arguments():
    # 键序颠倒的字典应得到相同的规范化字符串
    args1 = {"symbol": "510300", "limit": 100, "offset": 1}
    args2 = {"offset": 1, "symbol": "510300", "limit": 100}
    assert RepeatToolGuard.canonicalize_arguments(args1) == RepeatToolGuard.canonicalize_arguments(args2)

    # 嵌套结构键序颠倒
    nested1 = {"query": {"code": "600519", "days": 30}, "action": "search"}
    nested2 = {"action": "search", "query": {"days": 30, "code": "600519"}}
    assert RepeatToolGuard.canonicalize_arguments(nested1) == RepeatToolGuard.canonicalize_arguments(nested2)


def test_repeat_tool_guard_thresholds():
    guard = RepeatToolGuard(gentle_threshold=2, escalation_threshold=3)

    # 第一次调用：正常推进，无告警
    alert1 = guard.observe("admin_execute_shell", {"command": "find . -maxdepth 3"})
    assert alert1 is None

    # 第二次连续调用相同工具和入参：触发 Gentle 告警
    alert2 = guard.observe("admin_execute_shell", {"command": "find . -maxdepth 3"})
    assert alert2 is not None
    assert alert2.level == "gentle"
    assert alert2.count == 2
    assert "温和反思提醒" in alert2.message

    # 第三次连续调用相同工具和入参：触发 Escalation 严格阻断
    alert3 = guard.observe("admin_execute_shell", {"command": "find . -maxdepth 3"})
    assert alert3 is not None
    assert alert3.level == "escalation"
    assert alert3.count == 3
    assert "严格阻断警告" in alert3.message


def test_repeat_tool_guard_reset_on_different_tool():
    guard = RepeatToolGuard(gentle_threshold=2, escalation_threshold=3)

    guard.observe("admin_execute_shell", {"command": "git status"})
    # 换了命令
    alert = guard.observe("admin_execute_shell", {"command": "git diff"})
    assert alert is None

    # 换了工具
    alert = guard.observe("admin_read_source_code", {"file_path": "a.py"})
    assert alert is None


def test_repeat_tool_guard_reset():
    guard = RepeatToolGuard(gentle_threshold=2, escalation_threshold=3)

    guard.observe("admin_execute_shell", {"command": "ls -la"})
    guard.reset()
    # reset 之后第一次调用不告警
    alert = guard.observe("admin_execute_shell", {"command": "ls -la"})
    assert alert is None
