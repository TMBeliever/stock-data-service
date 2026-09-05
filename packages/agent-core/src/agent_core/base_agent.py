import json
import logging
import asyncio
import httpx
from typing import AsyncGenerator, Dict, Any, List, Optional
from ai_core.models import Message, ToolCall, ToolDefinition
from agent_core.tool import ToolRegistry
from agent_core.token_governor import TokenGovernor

logger = logging.getLogger(__name__)

def _check_tool_sensitivity(tc: ToolCall, sensitive_tools: Optional[List[str]] = None) -> tuple[bool, str]:
    """
    检查指定工具调用是否属于敏感/高危操作：
    - 在 sensitive_tools 清单内 (如 run_command, admin_execute_shell, write_file)
    - 针对包含 docker, brew, apt, npm, pkill, rm 等系统运维写命令特别拦截
    """
    sens_set = set(sensitive_tools or [
        "admin_modify_source_code",
        "admin_execute_shell",
        "admin_docker_manage",
        "admin_manage_service",
        "write_file",
        "run_command",
        "run_backtest_fast",
    ])
    
    if tc.name in sens_set:
        args = tc.arguments or {}
        cmd = str(args.get("command") or args.get("action") or "").strip()
        cmd_lower = cmd.lower()
        if "docker" in cmd_lower or tc.name == "admin_docker_manage":
            return True, f"涉及 Docker 容器基础设施管理: {cmd[:60] or 'docker'}"
        if "brew" in cmd_lower:
            return True, f"涉及 Homebrew 系统软件包变更: {cmd[:60]}"
        for kw in ["rm ", "kill", "pkill", "apt", "yum", "systemctl", "service", "chmod", "git push", "git reset", "drop"]:
            if kw in cmd_lower:
                return True, f"涉及系统核心运维/变更指令: {cmd[:60]}"
        return True, f"敏感系统运维/写操作工具: {tc.name}"
    return False, ""

class BaseAgent:
    """
    通用智能体运行基类 (Universal Agent Harness):
    封装 ReAct 循环核心、工具分发、Token 截断治理与多端流式事件协议
    """
    def __init__(
        self,
        name: str = "UniversalAgent",
        system_prompt: str = "你是一个高效、严谨且具备自主工具调用能力的通用 AI 助手。",
        tool_registry: Optional[ToolRegistry] = None,
        token_governor: Optional[TokenGovernor] = None,
        ai_core_url: str = "http://localhost:8070",
        max_steps: int = 8
    ):
        self.name = name
        self.system_prompt = system_prompt
        self.tool_registry = tool_registry or ToolRegistry()
        self.token_governor = token_governor or TokenGovernor()
        self.ai_core_url = ai_core_url.rstrip("/")
        self.max_steps = max_steps

    async def _call_llm_generate(
        self,
        messages: List[Message],
        tools: List[ToolDefinition],
        model: Optional[str] = None,
        provider: Optional[str] = None,
        temperature: Optional[float] = 0.2
    ) -> Dict[str, Any]:
        """向底层模型网关 (ai-core) 发起单次结构化生成请求"""
        url = f"{self.ai_core_url}/api/v1/ai/generate"
        payload = {
            "messages": [m.model_dump(exclude_none=True) for m in messages],
            "tools": [t.model_dump() for t in tools] if tools else None,
            "model": model,
            "provider": provider,
            "temperature": temperature
        }

        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code != 200:
                raise RuntimeError(f"AI Core error ({resp.status_code}): {resp.text}")
            return resp.json()

    async def stream_chat(
        self,
        prompt: Optional[str] = None,
        messages: Optional[List[Message]] = None,
        model: Optional[str] = None,
        provider: Optional[str] = None,
        temperature: Optional[float] = 0.2,
        system_prompt_override: Optional[str] = None,
        tool_category: Optional[str] = None,
        tool_registry_override: Optional[ToolRegistry] = None,
        execution_mode: str = "auto",
        sensitive_tools: Optional[List[str]] = None,
        approved_tool_calls: Optional[List[str]] = None,
        approved_tool_call: Optional[Dict[str, Any]] = None
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        通用 ReAct 流式交互调度器：
        自主循环调用模型与工具，并通过生成器 yield SSE 规范事件
        """
        active_sys_prompt = system_prompt_override or self.system_prompt
        active_registry = tool_registry_override or self.tool_registry

        # 1. 组装初始对话消息 (保持静态 Prompt Cache 友好排布)
        history: List[Message] = []
        history.append(Message.system(active_sys_prompt))

        if messages and len(messages) > 0:
            for m in messages:
                if m.role != "system":
                    history.append(m)
        elif prompt:
            history.append(Message.user(prompt))

        # 2. 准备工具定义列表并稳定排序 (Prompt Cache 命中优化)
        raw_tools = active_registry.to_definitions(category=tool_category)
        tools = self.token_governor.sort_tools_for_caching(raw_tools)

        logger.info(
            "Starting agent '%s' chat loop with %d tools mounted (max_steps=%d, mode=%s)",
            self.name, len(tools), self.max_steps, execution_mode
        )

        approved_set = set(approved_tool_calls or [])
        if approved_tool_call and approved_tool_call.get("id"):
            approved_set.add(approved_tool_call["id"])

        def is_tool_approved(tc: ToolCall, current_step: int) -> bool:
            if not approved_set:
                return False
            if tc.id in approved_set or tc.name in approved_set or "all" in approved_set:
                return True
            if current_step == 1 and len(approved_set) > 0:
                return True
            return False

        async def _execute_and_stream_tool(tc: ToolCall, current_step: int):
            """异步执行工具并并发推送流式进度 (tool_progress) 与驻守保活心跳 (ping)"""
            yield {
                "event": "tool_call",
                "data": json.dumps({
                    "id": tc.id,
                    "name": tc.name,
                    "arguments": tc.arguments,
                    "step": current_step
                }, ensure_ascii=False)
            }

            progress_queue: asyncio.Queue = asyncio.Queue()

            def on_tool_progress(chunk: str):
                try:
                    progress_queue.put_nowait(chunk)
                except Exception:
                    pass

            tool_task = asyncio.create_task(
                active_registry.execute(tc.name, tc.arguments, on_progress=on_tool_progress)
            )

            start_t = asyncio.get_event_loop().time()
            while not tool_task.done():
                try:
                    chunk = await asyncio.wait_for(progress_queue.get(), timeout=1.0)
                    yield {
                        "event": "tool_progress",
                        "data": json.dumps({
                            "id": tc.id,
                            "name": tc.name,
                            "delta": chunk,
                            "step": current_step
                        }, ensure_ascii=False)
                    }
                except asyncio.TimeoutError:
                    # 状态驻守心跳包，防止反向代理/网络超时断开
                    elapsed_sec = int(asyncio.get_event_loop().time() - start_t)
                    yield {
                        "event": "ping",
                        "data": json.dumps({
                            "id": tc.id,
                            "name": tc.name,
                            "step": current_step,
                            "elapsed": elapsed_sec
                        }, ensure_ascii=False)
                    }

            # 刷新所有残余进度队列项
            while not progress_queue.empty():
                chunk = progress_queue.get_nowait()
                yield {
                    "event": "tool_progress",
                    "data": json.dumps({
                        "id": tc.id,
                        "name": tc.name,
                        "delta": chunk,
                        "step": current_step
                    }, ensure_ascii=False)
                }

            try:
                raw_result = await tool_task
            except Exception as e:
                raw_result = f"Error executing tool '{tc.name}': {str(e)}"

            # Observation 观察截断保护
            truncated_result = self.token_governor.truncate_observation(raw_result)

            # 推送 tool_result 完成事件
            preview = truncated_result[:300] if len(truncated_result) > 300 else truncated_result
            yield {
                "event": "tool_result",
                "data": json.dumps({
                    "id": tc.id,
                    "name": tc.name,
                    "output_preview": preview,
                    "step": current_step
                }, ensure_ascii=False)
            }

            # 结果作为 tool 消息压入历史
            history.append(Message.tool_result(tool_call_id=tc.id, content=truncated_result, name=tc.name))

        step = 0
        consecutive_errors = 0  # 连续失败熏断器

        # 0. 优先分支：用户显式授权了上一轮被挂起的特定工具调用，直接执行它并推进后续 ReAct 循环
        if approved_tool_call and approved_tool_call.get("name"):
            step = int(approved_tool_call.get("step", 1))
            resume_tc = ToolCall(
                id=approved_tool_call.get("id", f"call_resume_{step}"),
                name=approved_tool_call["name"],
                arguments=approved_tool_call.get("arguments", {})
            )
            logger.info("Executing resumed approved tool call: %s (%s)", resume_tc.name, resume_tc.id)
            history.append(Message.assistant(content="", tool_calls=[resume_tc]))
            async for ev in _execute_and_stream_tool(resume_tc, step):
                yield ev

        while step < self.max_steps:
            step += 1

            # 3. 检查是否需要触发 Token Compaction
            if self.token_governor.needs_compaction(history, step):
                history = self.token_governor.compact_history(history)

            # 4. 调用模型生成
            try:
                ai_resp_data = await self._call_llm_generate(
                    messages=history,
                    tools=tools,
                    model=model,
                    provider=provider,
                    temperature=temperature
                )
            except Exception as e:
                err_msg = f"智能体模型推理调度异常: {str(e)}"
                logger.error(err_msg)
                yield {
                    "event": "message",
                    "data": json.dumps({"delta": f"\n\n> ⚠️ **执行异常**: {err_msg}", "role": "assistant"}, ensure_ascii=False)
                }
                yield {"event": "done", "data": json.dumps({"status": "error"})}
                return

            resp_content = ai_resp_data.get("content") or ""
            raw_tool_calls = ai_resp_data.get("tool_calls") or []

            # 5. 分支 A: 模型发起了工具调用 (Tool Calling)
            if raw_tool_calls and len(raw_tool_calls) > 0:
                parsed_calls = [
                    ToolCall(
                        id=c.get("id", f"call_{step}"),
                        name=c.get("name") or (c.get("function") or {}).get("name", ""),
                        arguments=c.get("arguments") or (c.get("function") or {}).get("arguments", {})
                    )
                    for c in raw_tool_calls
                ]

                # 记录 assistant 发起的 tool_calls
                history.append(Message.assistant(content=resp_content, tool_calls=parsed_calls))

                # 5.0 提取或生成本步骤的思考 (Thought)
                step_thought = resp_content.strip() if resp_content else ""
                if not step_thought:
                    tool_descs = []
                    for tc in parsed_calls:
                        t_obj = active_registry.get_tool(tc.name)
                        desc = t_obj.description.strip().split('\n')[0] if t_obj else tc.name
                        tool_descs.append(f"【{desc}】")
                    step_thought = f"正在推进第 {step} 步推演：调用 {'、'.join(tool_descs)} 采集关键数据与指标。"

                # 5.1 推送 thought 思考事件
                yield {
                    "event": "thought",
                    "data": json.dumps({
                        "step": step,
                        "thought": step_thought
                    }, ensure_ascii=False)
                }

                # 5.1.1 权限模式检查：拦截未授权的敏感操作
                for tc in parsed_calls:
                    needs_confirm = False
                    confirm_reason = ""

                    if execution_mode == "confirm_all":
                        needs_confirm = True
                        confirm_reason = f"严格管控模式: 所有工具调用均需授权 ({tc.name})"
                    elif execution_mode == "confirm_sensitive":
                        is_sens, sens_reason = _check_tool_sensitivity(tc, sensitive_tools)
                        if is_sens:
                            needs_confirm = True
                            confirm_reason = sens_reason

                    if needs_confirm and not is_tool_approved(tc, step):
                        logger.info("Tool call '%s' paused for approval: %s", tc.name, confirm_reason)
                        yield {
                            "event": "requires_approval",
                            "data": json.dumps({
                                "id": tc.id,
                                "name": tc.name,
                                "arguments": tc.arguments,
                                "reason": confirm_reason,
                                "step": step
                            }, ensure_ascii=False)
                        }
                        yield {
                            "event": "done",
                            "data": json.dumps({
                                "status": "waiting_approval",
                                "tool_call": {
                                    "id": tc.id,
                                    "name": tc.name,
                                    "arguments": tc.arguments,
                                    "reason": confirm_reason,
                                    "step": step
                                }
                            }, ensure_ascii=False)
                        }
                        return

                for tc in parsed_calls:
                    async for ev in _execute_and_stream_tool(tc, step):
                        yield ev

                # 工具返回结果分析：连续失败熏断
                last_tool_msgs = [m for m in history if m.role == "tool"]
                if last_tool_msgs:
                    last_result = last_tool_msgs[-1].content or ""
                    # 检测失败关键词
                    is_error = any(kw in last_result for kw in [
                        "Error", "error", "failed", "denied", "not found", "No such", "cannot", "失败", "异常"
                    ])
                    if is_error:
                        consecutive_errors += 1
                    else:
                        consecutive_errors = 0  # 成功则清零

                    if consecutive_errors >= 3:
                        error_summary = last_result[:400]
                        yield {
                            "event": "message",
                            "data": json.dumps({
                                "delta": f"\n\n> ⚠️ **连续工具调用失败 (3次)**，已中断重试。\n\n**最近错误**：\n```\n{error_summary}\n```\n\n请检查运行环境或提供更多上下文。",
                                "role": "assistant"
                            }, ensure_ascii=False)
                        }
                        yield {"event": "done", "data": json.dumps({"status": "finished"})}
                        return

                # 继续下一轮 ReAct 思考与综合
                continue

            # 6. 分支 B: 模型未调用工具，输出了最终回答
            if resp_content:
                # 若经历过多步工具调用，在输出正文前先发送就绪通知
                if step > 1:
                    yield {
                        "event": "thought",
                        "data": json.dumps({
                            "step": step,
                            "thought": "多维数据均已采集齐备，正在综合基本面、技术面与估值体系生成专业量化报告..."
                        }, ensure_ascii=False)
                    }
                # 分段逐块平滑推送最终文本
                chunk_size = 12
                for i in range(0, len(resp_content), chunk_size):
                    delta = resp_content[i:i + chunk_size]
                    yield {
                        "event": "message",
                        "data": json.dumps({"delta": delta, "role": "assistant"}, ensure_ascii=False)
                    }

            yield {"event": "done", "data": json.dumps({"status": "finished"})}
            return

        # 达到最大步数兜底处理
        yield {
            "event": "message",
            "data": json.dumps({
                "delta": f"\n\n> ⚠️ **步数限制**: 已达到最大工具执行深度 ({self.max_steps} 步)，任务强制终止。",
                "role": "assistant"
            }, ensure_ascii=False)
        }
        yield {"event": "done", "data": json.dumps({"status": "finished"})}
