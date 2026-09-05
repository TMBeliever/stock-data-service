import json
import logging
from typing import List, Dict, Any, Optional
from ai_core.models import Message, ToolDefinition

logger = logging.getLogger(__name__)


class TokenGovernor:
    """
    智能体 Token 治理器 v2:
    1. Observation 硬截断保护（防止长文本打爆上下文）
    2. Prompt Caching 友好排布（确保静态前缀稳定命中大模型缓存）
    3. 历史轨迹压缩（Compaction）——保留所有 tool_result 摘要，防止模型失忆
    """
    def __init__(
        self,
        max_observation_chars: int = 4000,
        max_observation_lines: int = 120,
        compaction_step_threshold: int = 12,
        max_history_tokens_estimate: int = 28000,
    ):
        self.max_observation_chars = max_observation_chars
        self.max_observation_lines = max_observation_lines
        self.compaction_step_threshold = compaction_step_threshold
        self.max_history_tokens_estimate = max_history_tokens_estimate

    def truncate_observation(self, raw_output: Any) -> str:
        """
        对工具输出进行安全硬截断：
        保留前段（结构定义/元数据）和尾部（最新结论/时间记录），
        杜绝万字日志或超长 JSON 撑爆上下文。
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

        # 按行与字符双重截断：保留头部（55%）与尾部（45%）
        head_lines_count = max(1, int(self.max_observation_lines * 0.55))
        tail_lines_count = max(1, self.max_observation_lines - head_lines_count)
        head_chars = max(100, int(self.max_observation_chars * 0.55))
        tail_chars = max(100, self.max_observation_chars - head_chars)

        head_lines = lines[:head_lines_count]
        head_text = "\n".join(head_lines)
        if len(head_text) > head_chars:
            head_text = head_text[:head_chars]

        tail_lines = lines[-tail_lines_count:] if total_lines > tail_lines_count else []
        tail_text = "\n".join(tail_lines)
        if len(tail_text) > tail_chars:
            tail_text = tail_text[-tail_chars:]

        omitted_lines = max(0, total_lines - len(head_lines) - len(tail_lines))
        omitted_chars = max(0, total_chars - len(head_text) - len(tail_text))

        notice = (
            f"\n\n... [⚠️ Output truncated by TokenGovernor: 中间省略 {omitted_lines} 行 / {omitted_chars} 字符; "
            f"头部 {len(head_text)} 字符 + 尾部 {len(tail_text)} 字符, 最新数据已保留在末尾] ...\n\n"
        )
        return head_text + notice + tail_text

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
        智能历史轨迹压缩 v2：
        - 保留：system prompt + 原始用户意图 + 最近 2 轮对话 (约 4 条消息)
        - 中间步骤：提取每个 tool_result 的关键摘要（不是全部丢弃！）
        - 防止模型因失忆而重复已完成的工作

        关键改进（vs v1）：
        v1 只保留最近 4 条，中间所有工具结果全丢。
        v2 将中间工具结果提炼成结构化摘要，模型始终知道之前做了什么、得到了什么。
        """
        if len(messages) <= 4:
            return messages

        system_msg = next((m for m in messages if m.role == "system"), None)
        first_user_msg = next((m for m in messages if m.role == "user"), None)
        # 保留最近 2 轮（约 4 条）
        recent_messages = messages[-4:]

        # 中间消息（除 system/first_user/recent 外）
        preserved_set = set()
        if system_msg:
            preserved_set.add(id(system_msg))
        if first_user_msg:
            preserved_set.add(id(first_user_msg))
        for m in recent_messages:
            preserved_set.add(id(m))

        intermediate_messages = [m for m in messages if id(m) not in preserved_set]

        if not intermediate_messages:
            return messages

        # 提取中间步骤摘要（关键改进：tool_result 不再直接丢弃）
        summary_points: List[str] = []
        for m in intermediate_messages:
            if m.role == "tool" and m.name:
                # 提取工具结果的核心信息（前 150 字符 + 后 80 字符）
                content = (m.content or "").strip()
                if len(content) > 230:
                    snippet = content[:150] + "..." + content[-80:]
                else:
                    snippet = content
                # 清理换行，压缩成单行摘要
                snippet_oneline = " | ".join(snippet.split("\n")[:3])
                summary_points.append(f"- [工具 `{m.name}`] → {snippet_oneline[:200]}")
            elif m.role == "assistant" and m.content:
                snippet = m.content[:100].replace("\n", " ")
                summary_points.append(f"- [模型分析] {snippet}...")

        # 最多保留 12 条摘要，超出部分取最近的
        if len(summary_points) > 12:
            omitted = len(summary_points) - 12
            summary_points = [f"  (另有 {omitted} 步中间记录已省略)"] + summary_points[-12:]

        summary_text = (
            "【历史上下文精简摘要 (Token Compaction v2)】\n"
            "前序步骤已完成的关键工具调用与发现（摘要保留，防止重复操作）：\n"
            + "\n".join(summary_points)
            + "\n\n请基于以上已掌握的事实继续推进后续任务，不要重复上述步骤。"
        )

        compacted: List[Message] = []
        if system_msg:
            compacted.append(system_msg)
        if first_user_msg and id(first_user_msg) not in {id(m) for m in compacted}:
            compacted.append(first_user_msg)
        compacted.append(Message.assistant(content=summary_text))
        compacted.extend(recent_messages)

        logger.info(
            "TokenGovernor compaction: %d msgs → %d msgs (摘要保留 %d 步工具记录)",
            len(messages), len(compacted), len(summary_points)
        )
        return compacted
