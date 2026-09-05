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
    通用智能体运行基类 v2 (Universal Agent Harness):
    - 并行工具执行 (无依赖工具 asyncio.gather 并发)
    - 错误反思机制 (工具失败后让模型分析原因再决策，而不是盲目熔断)
    - max_steps=20 适应复杂任务
    - 智能历史压缩（保留工具观察摘要，防止模型失忆）
    - 更细粒度的分块推送（chunk_size=8，更流畅的打字机效果）
    """
    def __init__(
        self,
        name: str = "UniversalAgent",
        system_prompt: str = "你是一个高效、严谨且具备自主工具调用能力的通用 AI 助手。",
        tool_registry: Optional[ToolRegistry] = None,
        token_governor: Optional[TokenGovernor] = None,
        ai_core_url: str = "http://localhost:8070",
        max_steps: int = 20
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
        """向底层模型网关发起单次结构化生成请求"""
        url = f"{self.ai_core_url}/api/v1/ai/generate"
        payload = {
            "messages": [m.model_dump(exclude_none=True) for m in messages],
            "tools": [t.model_dump() for t in tools] if tools else None,
            "model": model,
            "provider": provider,
            "temperature": temperature
        }
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code != 200:
                raise RuntimeError(f"AI Core error ({resp.status_code}): {resp.text}")
            return resp.json()

    async def _execute_tool_single(
        self,
        tc: ToolCall,
        current_step: int,
        active_registry: ToolRegistry,
        event_queue: asyncio.Queue
    ) -> str:
        """
        执行单个工具，将 SSE 事件放入共享队列，返回工具结果字符串。
        供并行执行时使用。
        """
        await event_queue.put({
            "event": "tool_call",
            "data": json.dumps({
                "id": tc.id, "name": tc.name,
                "arguments": tc.arguments, "step": current_step
            }, ensure_ascii=False)
        })

        progress_queue: asyncio.Queue = asyncio.Queue()

        def on_progress(chunk: str):
            try:
                progress_queue.put_nowait(chunk)
            except Exception:
                pass

        tool_task = asyncio.create_task(
            active_registry.execute(tc.name, tc.arguments, on_progress=on_progress)
        )

        start_t = asyncio.get_event_loop().time()
        while not tool_task.done():
            try:
                chunk = await asyncio.wait_for(progress_queue.get(), timeout=1.0)
                await event_queue.put({
                    "event": "tool_progress",
                    "data": json.dumps({
                        "id": tc.id, "name": tc.name,
                        "delta": chunk, "step": current_step
                    }, ensure_ascii=False)
                })
            except asyncio.TimeoutError:
                elapsed_sec = int(asyncio.get_event_loop().time() - start_t)
                await event_queue.put({
                    "event": "ping",
                    "data": json.dumps({
                        "id": tc.id, "name": tc.name,
                        "step": current_step, "elapsed": elapsed_sec
                    }, ensure_ascii=False)
                })

        # 刷新残余进度
        while not progress_queue.empty():
            chunk = progress_queue.get_nowait()
            await event_queue.put({
                "event": "tool_progress",
                "data": json.dumps({
                    "id": tc.id, "name": tc.name,
                    "delta": chunk, "step": current_step
                }, ensure_ascii=False)
            })

        try:
            raw_result = await tool_task
        except Exception as e:
            raw_result = f"Error executing tool '{tc.name}': {str(e)}"

        truncated_result = self.token_governor.truncate_observation(raw_result)
        preview = truncated_result[:400] if len(truncated_result) > 400 else truncated_result

        await event_queue.put({
            "event": "tool_result",
            "data": json.dumps({
                "id": tc.id, "name": tc.name,
                "output_preview": preview, "step": current_step
            }, ensure_ascii=False)
        })

        return truncated_result

    async def _execute_and_stream_tools(
        self,
        tool_calls: List[ToolCall],
        current_step: int,
        active_registry: ToolRegistry,
        history: List[Message]
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        并行执行多个工具：
        - 所有工具同时启动（asyncio.create_task）
        - 通过共享 event_queue 汇聚各工具的 SSE 事件流，按到达顺序 yield
        - 全部完成后按原始顺序将结果压入 history（遵循 OpenAI 规范）
        """
        event_queue: asyncio.Queue = asyncio.Queue()
        results: Dict[str, str] = {}

        async def run_one(tc: ToolCall):
            result = await self._execute_tool_single(tc, current_step, active_registry, event_queue)
            results[tc.id] = result
            await event_queue.put({"event": "_done_sentinel", "data": tc.id})

        tasks = [asyncio.create_task(run_one(tc)) for tc in tool_calls]
        done_count = 0

        while done_count < len(tasks):
            ev = await event_queue.get()
            if ev["event"] == "_done_sentinel":
                done_count += 1
            else:
                yield ev

        await asyncio.gather(*tasks, return_exceptions=True)

        # 按原始顺序压入 history
        for tc in tool_calls:
            result = results.get(tc.id, f"Error: tool '{tc.name}' produced no result")
            history.append(Message.tool_result(tool_call_id=tc.id, content=result, name=tc.name))

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
        ReAct 流式调度器 v2:
        - 工具轮次：非流式调用（需完整 tool_calls 结构）
        - 最终回答：分块流式推送（chunk_size=8，更流畅）
        - 并行工具执行（asyncio.create_task 并发）
        - 错误反思：失败预算耗尽先给模型一次反思机会，再失败才退出
        """
        active_sys_prompt = system_prompt_override or self.system_prompt
        active_registry = tool_registry_override or self.tool_registry

        # 1. 组装历史消息
        history: List[Message] = [Message.system(active_sys_prompt)]
        if messages and len(messages) > 0:
            for m in messages:
                if m.role != "system":
                    history.append(m)
        elif prompt:
            history.append(Message.user(prompt))

        # 2. 工具定义（稳定排序，利于 Prompt Cache）
        raw_tools = active_registry.to_definitions(category=tool_category)
        tools = self.token_governor.sort_tools_for_caching(raw_tools)

        logger.info(
            "Agent '%s' starting: %d tools, max_steps=%d, mode=%s",
            self.name, len(tools), self.max_steps, execution_mode
        )

        approved_set = set(approved_tool_calls or [])
        if approved_tool_call and approved_tool_call.get("id"):
            approved_set.add(approved_tool_call["id"])

        def is_tool_approved(tc: ToolCall, current_step: int) -> bool:
            if not approved_set:
                return False
            return tc.id in approved_set or tc.name in approved_set or "all" in approved_set

        step = 0
        error_budget = 3        # 连续全量失败预算
        reflection_used = False  # 是否已使用过反思机会

        # ── 0. 优先恢复用户授权的工具调用 ──
        if approved_tool_call and approved_tool_call.get("name"):
            step = int(approved_tool_call.get("step", 1))
            resume_tc = ToolCall(
                id=approved_tool_call.get("id", f"call_resume_{step}"),
                name=approved_tool_call["name"],
                arguments=approved_tool_call.get("arguments", {})
            )
            logger.info("Resuming approved tool: %s (%s)", resume_tc.name, resume_tc.id)
            history.append(Message.assistant(content="", tool_calls=[resume_tc]))
            async for ev in self._execute_and_stream_tools([resume_tc], step, active_registry, history):
                yield ev

        # ── 主 ReAct 循环 ──
        while step < self.max_steps:
            step += 1

            # Token 压缩检查
            if self.token_governor.needs_compaction(history, step):
                history = self.token_governor.compact_history(history)

            # ── 4. 调用模型 ──
            try:
                ai_resp = await self._call_llm_generate(
                    messages=history, tools=tools,
                    model=model, provider=provider, temperature=temperature
                )
            except Exception as e:
                err_msg = f"智能体推理异常: {str(e)}"
                logger.error(err_msg)
                yield {
                    "event": "message",
                    "data": json.dumps({"delta": f"\n\n> ⚠️ **推理异常**: {err_msg}", "role": "assistant"}, ensure_ascii=False)
                }
                yield {"event": "done", "data": json.dumps({"status": "error"})}
                return

            resp_content = ai_resp.get("content") or ""
            raw_tool_calls = ai_resp.get("tool_calls") or []

            # ── 5A. 模型发起工具调用 ──
            if raw_tool_calls:
                parsed_calls = [
                    ToolCall(
                        id=c.get("id", f"call_{step}_{i}"),
                        name=c.get("name") or (c.get("function") or {}).get("name", ""),
                        arguments=c.get("arguments") or (c.get("function") or {}).get("arguments", {})
                    )
                    for i, c in enumerate(raw_tool_calls)
                ]

                history.append(Message.assistant(content=resp_content, tool_calls=parsed_calls))

                # 生成 Thought
                if resp_content.strip():
                    step_thought = resp_content.strip()
                else:
                    tool_descs = []
                    for tc in parsed_calls:
                        t_obj = active_registry.get_tool(tc.name)
                        desc = t_obj.description.strip().split('\n')[0][:28] if t_obj else tc.name
                        tool_descs.append(f"【{desc}】")
                    parallel_hint = "（并行）" if len(parsed_calls) > 1 else ""
                    step_thought = f"第 {step} 步 {parallel_hint}：{'、'.join(tool_descs[:4])}{'...' if len(tool_descs) > 4 else ''}"

                yield {
                    "event": "thought",
                    "data": json.dumps({"step": step, "thought": step_thought}, ensure_ascii=False)
                }

                # 权限检查（遇到需要授权的工具立即挂起，等用户确认）
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
                        logger.info("Tool '%s' paused for approval: %s", tc.name, confirm_reason)
                        yield {
                            "event": "requires_approval",
                            "data": json.dumps({
                                "id": tc.id, "name": tc.name,
                                "arguments": tc.arguments,
                                "reason": confirm_reason, "step": step
                            }, ensure_ascii=False)
                        }
                        yield {
                            "event": "done",
                            "data": json.dumps({
                                "status": "waiting_approval",
                                "tool_call": {
                                    "id": tc.id, "name": tc.name,
                                    "arguments": tc.arguments,
                                    "reason": confirm_reason, "step": step
                                }
                            }, ensure_ascii=False)
                        }
                        return

                # ── 并行执行所有工具 ──
                async for ev in self._execute_and_stream_tools(parsed_calls, step, active_registry, history):
                    yield ev

                # ── 错误检测 ──
                recent_results = [m for m in history if m.role == "tool"][-len(parsed_calls):]
                error_msgs = [
                    m for m in recent_results
                    if any(kw in (m.content or "") for kw in [
                        "Error", "error", "failed", "denied", "not found",
                        "No such", "cannot", "失败", "异常", "Permission", "Timeout"
                    ])
                ]

                # 只有"本轮工具全部失败"才消耗错误预算
                all_failed = len(error_msgs) > 0 and len(error_msgs) == len(parsed_calls)

                if all_failed:
                    error_budget -= 1

                    if error_budget <= 0:
                        if not reflection_used:
                            # ── 给模型一次反思机会 ──
                            reflection_used = True
                            error_budget = 2  # 反思后再给 2 次预算
                            error_summary = "\n".join([
                                f"- 工具 `{m.name}`: {(m.content or '')[:250]}"
                                for m in error_msgs
                            ])
                            history.append(Message.user(
                                f"工具调用连续失败：\n{error_summary}\n\n"
                                "请分析错误原因并决定下一步：\n"
                                "1. 能换一种方式完成任务吗？（换工具/换参数）\n"
                                "2. 如果是环境问题（权限/Docker/网络），请直接解释并给用户提供手动修复步骤，停止重试。\n"
                                "3. 如果可以继续，请立即执行下一步。"
                            ))
                            yield {
                                "event": "thought",
                                "data": json.dumps({
                                    "step": step,
                                    "thought": "🔍 检测到连续工具失败，正在反思原因并调整策略..."
                                }, ensure_ascii=False)
                            }
                            continue  # 让模型基于反思决定下一步

                        else:
                            # 已反思过，仍然失败 → 告知用户原因退出
                            last_error = (error_msgs[-1].content or "")[:400]
                            yield {
                                "event": "message",
                                "data": json.dumps({
                                    "delta": (
                                        "\n\n> ⚠️ **任务受阻**\n\n"
                                        "经过分析和策略调整后，任务仍无法完成，运行环境存在系统级障碍。\n\n"
                                        f"**最后错误**：\n```\n{last_error}\n```\n\n"
                                        "**建议**：检查环境权限，或将错误信息提供给管理员处理。"
                                    ),
                                    "role": "assistant"
                                }, ensure_ascii=False)
                            }
                            yield {"event": "done", "data": json.dumps({"status": "finished"})}
                            return
                else:
                    error_budget = 3  # 有成功结果则重置预算

                continue

            # ── 5B. 模型输出最终回答 ──
            if resp_content:
                if step > 1:
                    yield {
                        "event": "thought",
                        "data": json.dumps({
                            "step": step,
                            "thought": "📋 数据采集完毕，正在生成最终分析..."
                        }, ensure_ascii=False)
                    }

                # 分块流式推送（chunk_size=8，更流畅的打字机效果）
                chunk_size = 8
                for i in range(0, len(resp_content), chunk_size):
                    delta = resp_content[i:i + chunk_size]
                    yield {
                        "event": "message",
                        "data": json.dumps({"delta": delta, "role": "assistant"}, ensure_ascii=False)
                    }
                    await asyncio.sleep(0)  # 让事件循环有机会推送 SSE

            yield {"event": "done", "data": json.dumps({"status": "finished"})}
            return

        # 达到 max_steps 上限
        yield {
            "event": "message",
            "data": json.dumps({
                "delta": (
                    f"\n\n> ⚠️ **步数上限 ({self.max_steps} 步)**\n\n"
                    "任务规模超出单次执行预算。已完成的中间步骤已保存。\n"
                    "你可以继续追问，我会基于已有结果继续推进。"
                ),
                "role": "assistant"
            }, ensure_ascii=False)
        }
        yield {"event": "done", "data": json.dumps({"status": "finished"})}
