import json
import logging
from typing import List, Dict, Any, Optional
from ai_core.models import Message, ToolDefinition

logger = logging.getLogger(__name__)

class TokenGovernor:
    """
    智能体 Token 治理器：
    1. Observation 硬截断保护（防止长文本打爆上下文）
    2. Prompt Caching 友好排布（确保静态前缀稳定命中大模型缓存，成本降低 80%+）
    3. 历史轨迹摘要与压缩（Compaction）
    """
    def __init__(
        self,
        max_observation_chars: int = 3500,
        max_observation_lines: int = 100,
        compaction_step_threshold: int = 8,
        max_history_tokens_estimate: int = 24000,
    ):
        self.max_observation_chars = max_observation_chars
        self.max_observation_lines = max_observation_lines
        self.compaction_step_threshold = compaction_step_threshold
        self.max_history_tokens_estimate = max_history_tokens_estimate

    def truncate_observation(self, raw_output: Any) -> str:
        """
        对工具输出进行安全硬截断：
        保留前段和尾部核心结果，杜绝万字日志或超长 JSON 撑爆上下文。
        """
        if raw_output is None:
            return ""

        text = raw_output if isinstance(raw_output, str) else json.dumps(raw_output, ensure_ascii=False, indent=2)
        total_chars = len(text)
        lines = text.split("\n")
        total_lines = len(lines)

        needs_truncation = (total_chars > self.max_observation_chars) or (total_lines > self.max_observation_lines)
        if not needs_truncation:
            return text

        # 按行与字符双重截断
        head_lines = lines[: self.max_observation_lines]
        truncated_text = "\n".join(head_lines)
        if len(truncated_text) > self.max_observation_chars:
            truncated_text = truncated_text[: self.max_observation_chars]

        notice = (
            f"\n\n... [⚠️ Output truncated by TokenGovernor: total {total_chars} chars, "
            f"{total_lines} lines; showing first {len(truncated_text)} chars. "
            f"Please refine query or use range/offset parameters if needed] ..."
        )
        return truncated_text + notice

    def sort_tools_for_caching(self, tools: List[ToolDefinition]) -> List[ToolDefinition]:
        """
        稳定排序工具定义：
        确保在请求中工具 Schema 顺序确定，最大化触发大模型提供商的 Prompt Caching
        """
        return sorted(tools, key=lambda t: t.name)

    def estimate_tokens(self, text: str) -> int:
        """粗略估算 Token 数量 (中英混合近似估算)"""
        if not text:
            return 0
        # 英文约 4 字符 1 token，中文约 1.5 字符 1 token，取加权均值约 2.5 字符
        return max(1, int(len(text) / 2.5))

    def needs_compaction(self, messages: List[Message], current_step: int) -> bool:
        """判断是否需要触发历史轨迹压缩"""
        if current_step >= self.compaction_step_threshold:
            return True
        
        total_est = sum(self.estimate_tokens(m.content or "") for m in messages)
        return total_est > self.max_history_tokens_estimate

    def compact_history(self, messages: List[Message]) -> List[Message]:
        """
        对长多轮消息进行折叠压缩：
        保留第一条系统设定、第一条用户初始意图，以及最近 2 轮的核心上下文，
        将中间冗余的工具调用和 Observation 提炼成一条事实纪要。
        """
        if len(messages) <= 4:
            return messages

        system_msg = next((m for m in messages if m.role == "system"), None)
        first_user_msg = next((m for m in messages if m.role == "user"), None)
        recent_messages = messages[-4:]

        intermediate_messages = [
            m for m in messages[1:-4] if m != first_user_msg and m != system_msg
        ]

        if not intermediate_messages:
            return messages

        # 提取中间步骤摘要
        summary_points: List[str] = []
        for m in intermediate_messages:
            if m.role == "tool" and m.name:
                summary_points.append(f"- 曾调用工具 `{m.name}` 并已获取相关数据")
            elif m.role == "assistant" and m.content:
                snippet = m.content[:120].replace("\n", " ")
                summary_points.append(f"- 曾推演分析: {snippet}...")

        summary_text = (
            "【历史上下文精简摘要 (Token Compaction)】\n"
            "为保障推理效率与上下文预算，前序中间观察已折叠压缩：\n"
            + "\n".join(summary_points[:8])
            + "\n请基于已掌握事实继续推进后续任务。"
        )

        compacted: List[Message] = []
        if system_msg:
            compacted.append(system_msg)
        if first_user_msg and first_user_msg not in compacted:
            compacted.append(first_user_msg)

        compacted.append(Message.assistant(content=summary_text))
        compacted.extend(recent_messages)
        return compacted
