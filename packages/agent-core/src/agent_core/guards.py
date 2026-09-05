import json
import logging
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class GuardAlert:
    """守卫拦截与反思告警对象 (借鉴 DSH repeat-tool-reminder 规范)"""
    tool_name: str
    count: int = 0
    level: str = "gentle"  # "gentle" | "escalation"
    message: str = ""
    canonical_arguments: str = ""


class RepeatToolGuard:
    """
    循环卫生与防重复调用守卫 (Repeat Tool Guard):
    
    【工业级设计背景 (对齐 DeepSeek Harness dsh-guard-repeat-tool-reminder)】:
    在复杂长链路推演中，大模型在遭遇非预期返回或部分空结果时，极易陷入
    连续发起相同工具名与相同参数的“复读机 / 死循环”陷阱，浪费 Token 并消耗用户等待时间。
    
    本守卫在每个 Agent 步骤执行后对工具调用签名做确定性规范化 (Canonicalization)，
    进行链式追踪：
    1. 当相同调用连续出现第 2 次时：注入温和反思警示 (Gentle Reminder)；
    2. 当相同调用连续出现第 3 次及以上时：注入严格升级阻断 (Escalation Alert)，勒令模型放弃重试。
    3. 收到新用户指令或调用不同工具时自动重置计数。
    """
    def __init__(
        self,
        gentle_threshold: int = 2,
        escalation_threshold: int = 3,
        max_preview_chars: int = 200,
        ignored_tools: Optional[List[str]] = None
    ):
        self.gentle_threshold = gentle_threshold
        self.escalation_threshold = escalation_threshold
        self.max_preview_chars = max_preview_chars
        self.ignored_tools = set(ignored_tools or [])
        
        # 链状态：(last_call_key, consecutive_count)
        self._last_key: Optional[str] = None
        self._repeat_count: int = 0

    @staticmethod
    def canonicalize_arguments(arguments_value: Any) -> str:
        """
        深度递归键排序，确保任何顺序不同但键值相同的 JSON 参数得到一致的规范化签名。
        例如 {"b": 2, "a": 1} 与 {"a": 1, "b": 2} 规范化结果完全相同。
        """
        def _sort_val(v):
            if isinstance(v, dict):
                return {k: _sort_val(v[k]) for k in sorted(v.keys())}
            elif isinstance(v, list):
                return [_sort_val(item) for item in v]
            return v

        try:
            if isinstance(arguments_value, str):
                try:
                    parsed = json.loads(arguments_value)
                    return json.dumps(_sort_val(parsed), ensure_ascii=False, separators=(',', ':'))
                except Exception:
                    return arguments_value.strip()
            elif isinstance(arguments_value, dict):
                return json.dumps(_sort_val(arguments_value), ensure_ascii=False, separators=(',', ':'))
            return str(arguments_value)
        except Exception:
            return str(arguments_value)

    def observe(self, tool_name: str, arguments: Any) -> Optional[GuardAlert]:
        """
        记录并评估一次工具调用，若触发重复阈值则返回相应的守卫告警对象。
        """
        if tool_name in self.ignored_tools:
            return None

        canonical_args = self.canonicalize_arguments(arguments)
        call_key = f"{tool_name}::{canonical_args}"

        if self._last_key == call_key:
            self._repeat_count += 1
        else:
            self._last_key = call_key
            self._repeat_count = 1

        # 触发判断
        if self._repeat_count >= self.escalation_threshold:
            preview = canonical_args[:self.max_preview_chars]
            if len(canonical_args) > self.max_preview_chars:
                preview += f"... (+{len(canonical_args) - self.max_preview_chars} chars)"

            alert_msg = (
                f"【循环卫生守卫 · 严格阻断警告】\n"
                f"检测到您正在连续第 {self._repeat_count} 次发起完全相同的工具调用！\n"
                f"- 工具: `{tool_name}`\n"
                f"- 参数: `{preview}`\n\n"
                "重复执行无法产生新的事实或推进任务。请立即停止重复调用该工具！\n"
                "请严格基于此前已获得的全部信息，换用其他参数、使用其他工具，或者直接向用户汇报当前已采集的事实并给出结论。"
            )
            logger.warning("RepeatToolGuard ESCALATION: %s (count=%d)", tool_name, self._repeat_count)
            return GuardAlert(
                tool_name=tool_name,
                count=self._repeat_count,
                level="escalation",
                message=alert_msg,
                canonical_arguments=canonical_args
            )

        elif self._repeat_count == self.gentle_threshold:
            alert_msg = (
                f"【循环卫生守卫 · 温和反思提醒】\n"
                f"您正在重复执行上一步完全相同的工具调用 `{tool_name}`（参数完全一致）。\n"
                "请仔细核对并深度利用前序已获取的执行结果：若当前任务尚未闭环，请尝试调整参数或改用其他策略工具，切勿陷入重复执行。"
            )
            logger.info("RepeatToolGuard GENTLE: %s (count=%d)", tool_name, self._repeat_count)
            return GuardAlert(
                tool_name=tool_name,
                count=self._repeat_count,
                level="gentle",
                message=alert_msg,
                canonical_arguments=canonical_args
            )

        return None

    def reset(self):
        """重置守卫链状态（在用户输入新轮次消息时调用）"""
        self._last_key = None
        self._repeat_count = 0
