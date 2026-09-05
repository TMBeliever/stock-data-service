# Agent Core (Universal Agent Harness)

`agent-core` 是一个通用的智能体运行时底座（Harness），具备类似 DeepSeek Harness (dsh) / Claude Code / Codex 的核心调度能力：
- **ReAct 循环**：多轮 Think -> Act -> Observe -> Synthesize 自主执行循环。
- **工具生态**：支持 `@tool` 装饰器、`ToolRegistry` 动态分类挂载、内置 Shell / Filesystem 工具。
- **MCP 原生集成**：支持通过标准 Model Context Protocol (MCP) 动态连接任意外部数据中台与工具服务。
- **Token 治理**：内置 Observation 观察截断、Prompt Cache 友好布局、长时任务轨迹压缩。
- **流式 SSE 协议**：标准实时事件分发 (`tool_call`, `tool_result`, `message`, `token_usage`, `done`)。
