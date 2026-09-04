# AI-Core 基础设施引擎

`ai-core` 是量化系统 Monorepo 的纯粹通用 AI 模型接入基础设施底座，提供统一、非业务耦合的 LLM 调用能力。

## 核心特性
- **双驱动统一适配**：
  - **APIKeyProvider**：原生兼容 OpenAI 协议，开箱支持 DeepSeek、OpenAI、Claude、Qwen 以及私有大模型网关。
  - **CLIProcessProvider**：安全异步子进程执行，支持调度本地安装的 Claude Code、Codex CLI、Aider 或 Ollama。
- **流式优先**：完整支持逐 Token 的异步流式输出（SSE / 子进程实时管道流）。
- **统一工具调用 (Tool Calling)**：标准化函数定义序列化与结果解析。
- **面向未来 Agent 预留**：内置 `BaseAgent` 状态机循环骨架，供上层领域 Agent（如量化策略 Agent）继承扩展。
