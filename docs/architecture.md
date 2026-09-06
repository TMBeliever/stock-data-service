# 全栈量化工程与自主智能体系统架构设计规范
## (System Architecture & Technical Specification)

本文档定义了本量化工程系统的总体架构设计哲学、多层解耦规范、量化投研与撮合风控模型、自主智能体（Agent）运行时、以及算力网关（AI-Core）的高并发无状态独占预热待命池与全系模型矩阵。

---

## 一、 总体设计哲学与分层架构拓扑

系统采用 **Polyglot Monorepo（多语言统一工作区）** 架构，将底层通用底座（`packages/*`）、领域微服务中枢（`services/*`）与前端看板交互终端（`apps/*`）严格解耦，遵循**单一职责、单向依赖、接口即契约**的工程哲学。

```mermaid
flowchart TB
    subgraph Clients["1. 终端展示与人机交互层 (Apps & Clients)"]
        direction LR
        App_Web["apps/web-admin<br/>Vue3 + Monaco Editor + ECharts<br/>(智能量化投研与看盘工作台)"]
        Client_CLI["Claude CLI / 开发者终端<br/>(原生 Anthropic 交互协议)"]
        Client_3rd["第三方量化系统 / Dify / 微信小程序<br/>(OpenAI 标准协议)"]
    end

    subgraph Gateway["2. 统一网络接入与反向代理层 (Nginx Gateway: Port 80)"]
        Nginx_Proxy["Nginx 反向代理与路由分发<br/>(/ -> 3000, /api/v1/quant/ -> 8080, /api/v1/agent/ -> 8090, /v1/ & /messages -> 8070)"]
    end

    subgraph MicroServices["3. 业务微服务集群 (services/*)"]
        direction TB
        S_Agent["services/quant-agent (Port 8090)<br/>量化自治与系统自愈专家 Agent<br/>(系统巡检、代码热修补审计、终端执行)"]
        S_Quant["services/quant-server (Port 8080)<br/>策略注册与管理、动态回测执行引擎<br/>(策略热重载、KPI 分析计算)"]
        S_Common["services/common-server (Port 8000)<br/>统一用户中心、JWT 鉴权、RBAC 角色守卫"]
    end

    subgraph ComputeEngine["4. 双引擎无状态算力网关 (packages/ai-core: Port 8070)"]
        direction TB
        subgraph AICore_Inside["ai-core 算力网关内部拓扑"]
            AI_Router["智能模型矩阵路由器 (resolve_agt_model)<br/>支持 agt-* 全系模型矩阵与 Claude 自动对齐"]
            AI_Pool["独占预热待命池 (Pre-warmed Standby Pool)<br/>4 进程待命 / 0ms 冷启动 / 用完即焚 / 2s 错峰启动 / 5min 归零"]
            AI_Protocols["双协议适配器<br/>OpenAI (/v1/chat/completions) & Anthropic (/v1/messages)"]
            AI_Key_Fallback["备用外部 API Key 网关 (OpenRouter / Gemini API)"]
        end
    end

    subgraph CoreSDKs["5. 核心算法包与智能体 SDK 底座 (packages/*)"]
        direction LR
        SDK_Agent["packages/agent-core<br/>ReAct 认知决策循环<br/>Sticky CWD 工作区治理<br/>TokenGovernor 流量守卫<br/>Approval 人在回路审批"]
        SDK_Quant["packages/quant-core<br/>Point-in-Time 杜绝未来函数<br/>A股制度 (T+1, 印花税, 整手)<br/>多资产因子计算库 (SMA, RSI, ATR)"]
        SDK_Data["packages/stock-data<br/>全球行情中台 (TuShare/AkShare/Sina)<br/>DuckDB + 本地 Parquet 列式存储<br/>除权除息因子清洗"]
    end

    %% 交互链路
    Clients --> Gateway
    Gateway --> MicroServices
    Gateway --> ComputeEngine

    S_Agent --> SDK_Agent
    S_Agent --> ComputeEngine
    S_Quant --> SDK_Quant
    SDK_Quant --> SDK_Data
    S_Common <-->|"SQLite / Postgres"| DB_Auth[(auth.db)]
    SDK_Data <-->|"Parquet 零拷贝直读"| DB_Market[(market.parquet)]
```

---

## 二、 核心子系统架构与职责契约

### 2.1 算力网关微服务 (`packages/ai-core`)

作为全系统的认知算力引擎，`ai-core` 负责向上层提供毫秒级、零污染、高吞吐的通用大模型流式管道，兼备**宿主机原生推演能力**与**公网 API Key 兜底能力**。

```mermaid
flowchart TD
    Req["客户端请求<br/>(Claude CLI / quant-agent / Dify)"] --> Prot["双协议路由适配<br/>/v1/messages 或 /v1/chat/completions"]
    Prot --> Auth{"固定 Key 鉴权<br/>(GATEWAY_API_KEY)"}
    Auth -- 失败 --> Err401["401 Unauthorized"]
    Auth -- 成功 --> ModelCheck{"resolve_agt_model(model)"}

    ModelCheck -- "agt-* / claude-* / agy" --> StandbyPool["独占预热待命池 (PrewarmedProcessPool)"]
    ModelCheck -- "外部模型 (minimax, gpt-4o 等)" --> KeyGateway["API Key 驱动网关 (OpenRouter / Gemini)"]

    subgraph PoolDetail["独占预热待命池核心生命周期"]
        StandbyPool --> Acquire["原子独占租借 Worker (0ms 延迟)"]
        Acquire --> Execute["原子写入 stdin (完整上下文) 并流式读取 stdout"]
        Execute --> Terminate["用完即焚：terminate() 强杀进程并关闭管道 (100% 物理隔离)"]
        Terminate --> GentleFill["错峰平滑补位 (2.0s 延迟拉起新待命进程)"]
        Execute -. "客户端中途断开 (Ctrl+C)" .-> DisconnectInterrupt["ASGI 捕获 http.disconnect -> 立即 SIGKILL 强杀销毁"]
    end
```

#### 1. 彻底无状态（100% Stateless）设计
- **客户端自持上下文**：客户端（Claude CLI / Agent）在请求体内传递当前多轮对话的全量消息数组，网关仅做原子消费并推入进程管道；
- **剥离会话数据库与状态参数**：严禁传递 `--conversation`、`-c`、`--session-id`、`--resume` 参数，彻底去除 SQLite 会话缓存依赖，消除上下文双倍叠加与内存膨胀风险；
- **剥离原生 Agent 工具拦截与 Git 扫描**：启动参数固定采用 `-p ""` 配合 `-y`（YOLO 自动非交互模式），并在隔离的临时无代码沙箱 `/tmp/quant_ai_clean_sandbox` 中运行，使其纯化为高吞吐、纯净的大模型流式输出管道。

#### 2. 独占预热待命池（Pre-warmed Standby Pool）
- **零冷启动延迟**：活跃期常态维护 4 个已启动并初始化完毕的子进程（每个占用约 160MB，总计约 640MB 内存），请求到达时秒级直接获取；
- **单次独占租借 + 用完即焚（Single-Use Lease）**：
  - 一个进程同一时刻只服务一个请求；
  - 单次推演完成（或发生异常）后，立即执行 `worker.terminate()` 强杀销毁；
  - 彻底杜绝复用进程导致的 `stdout` 缓冲区残留、多请求串流、跨会话粘包问题；
- **温和错峰补位（Gentle Staggered Warmup）**：
  - 为防止并发拉起多个 Node 进程瞬间打满 CPU（飙升至 100%）导致服务器假死，补位协程强制在每次拉起前引入 `CLI_SPAWN_STAGGER_DELAY = 2.0s` 错峰休眠；
- **空闲自动归零（Scale-to-Zero）**：
  - 后台轮询巡检协程每 15 秒检测一次最后请求时间；
  - 闲置超过 5 分钟（`CLI_POOL_IDLE_TIMEOUT = 300s`）无请求，自动杀死所有待命进程，服务器内存彻底释放归零；
- **手动打断即时熔断机制（Ctrl+C Disconnect Handling）**：
  - 底层基于 `EventSourceResponse` 监听 ASGI `http.disconnect` 事件；
  - 客户端按 `Ctrl+C` 断开连接的毫秒内，触发 `asyncio.CancelledError`，执行 `try...finally` 立即强杀子进程，释放系统资源，绝不残留孤儿僵尸进程。

#### 3. `agt-xxxxxxx` 全系模型矩阵路由规范
统一对外模型命名标准，支持原生模型自动解析与映射：

| 客户端请求模型 (`model`) | 映射驱动 | 实际执行模型参数 (`-m`) | 定位与能力说明 |
| :--- | :--- | :--- | :--- |
| `agt-gemini-3.8-flash` / `agt-flash` | `cli` (agy) | `gemini-3.8-flash` | 默认超高速主力模型，兼具速度与强推理 |
| `agt-gemini-3.7-flash` | `cli` (agy) | `gemini-3.7-flash` | 平衡型快速推演基座 |
| `agt-gemini-3.6-flash` | `cli` (agy) | `gemini-3.6-flash` | 稳定经典多模态基座 |
| `agt-gemini-3.1-pro` / `agt-pro` | `cli` (agy) | `gemini-3.1-pro` | 深度复杂推理、超长上下文分析基座 |
| `agt-claude-sonnet-4.6` / `agt-sonnet` | `cli` (agy) | `claude-sonnet-4.6` | 宿主机 Claude 思考主力模型 |
| `agt-claude-opus-4.6` / `agt-opus` | `cli` (agy) | `claude-opus-4.6` | 顶级大模型架构深度设计基座 |
| `agt-gpt-oss-120b` | `cli` (agy) | `gpt-oss-120b` | 开源大模型旗舰基座 |
| `claude-3-5-sonnet*` / `claude-3-7-sonnet*` | `cli` (agy) | `claude-sonnet-4.6` | Claude CLI 客户端无缝自动路由 |
| `claude-3-opus*` | `cli` (agy) | `claude-opus-4.6` | Claude CLI 顶级模型自动对齐 |
| `minimax/minimax-m3:free` 等外部模型 | `key` | 原始模型名称 | 自动走 API Key 外部网关（如 OpenRouter） |

---

### 2.2 自主智能体运行时内核 (`packages/agent-core` & `services/quant-agent`)

量化专家智能体具备系统自愈、运维巡检、回测参数调优与代码审计能力，采用全链路人在回路安全设计。

```mermaid
flowchart LR
    User["量化研究员 / 开发者"] --> Agent["quant-agent (专家智能体)"]
    Agent --> Think["ReAct 决策与推理循环"]
    Think --> Gov{"Token 流量守卫<br/>(TokenGovernor)"}
    Gov -- 超额拦截 --> Stop["熔断保护"]
    Gov -- 放行 --> ToolCheck{"敏感操作识别<br/>(文件写 / Shell 执行)"}
    ToolCheck -- 敏感操作 --> Approval["挂起等待用户审批 (Approval Loop)"]
    Approval -- 拒绝 --> Rollback["安全回滚与撤回"]
    Approval -- 批准 --> Exec["安全执行工具 (Dynamic Tool Registry)"]
    ToolCheck -- 安全只读 --> Exec
    Exec --> CWD["工作区目录持久化 (Sticky CWD)"]
    CWD --> Output["生成响应与量化分析图表"]
```

1. **ReAct 认知循环**：支持多轮思考（Thought）、行动（Action）、观察（Observation）全自主闭环；
2. **工作空间目录记忆（Sticky CWD Navigation）**：维护会话级真实工作路径，支持开发者通过自然语言跨目录操作，跨命令保持当前工作目录；
3. **动态工具注册中心（Dynamic Tool Registry）与 RBAC 权限体系**：
   - 基础工具：系统健康巡检、容器状态监测、回测任务触发；
   - 核心工具：源代码审计、安全代码补丁（内置预检与自动回滚机制）、沙箱终端执行；
4. **Token 流量守卫（TokenGovernor）**：滑动窗口限流，杜绝模型死循环调用导致账单击穿；
5. **人在回路安全审批（Human-in-the-loop Approval）**：涉及文件覆盖、执行外部命令等高危动作自动进入挂起状态，通过 Web 交互卡片等待人工授权后方可执行。

---

### 2.3 量化投研内核 (`packages/quant-core`)

量化内核严格遵循真实交易微观结构，保证回测收益真实可落地。

```mermaid
sequenceDiagram
    autonumber
    participant D as stock-data (数据中台)
    participant E as BacktestEngine (回测引擎)
    participant S as BaseStrategy (策略实例)
    participant R as RiskEngine (事前风控)
    participant B as SimulatedBroker (撮合系统)
    participant P as Portfolio (账户账本)

    Note over E,D: 时间切片轮转 (Timestamp: T)
    D->>E: 供给 Point-in-Time Bar 切片 (杜绝未来函数)
    E->>S: 触发 on_bar(bar)
    S->>S: 计算指标因子 (SMA, RSI, ATR)
    S->>E: 提交订单 (Order: 买入/卖出/目标持仓)
    E->>R: 事前风控校验 (涨跌停校验, 资金限额, 停牌过滤)
    R-->>E: 风控通过
    E->>B: 撮合订单 (次日开盘价 Next-Open 或挂单限价)
    B->>P: 扣除交易滑点、万2.5佣金、卖出万五印花税
    B->>P: 划拨持仓 (当日买入执行 T+1 锁定)
    B-->>E: 生成成交流水 (Trade)
    E->>S: 回调 on_trade(trade)
    Note over E,P: 闭市清算 (settle_day_end 解锁可用持仓，计算当日单位净值与最大回撤)
```

- **Code Once, Run Anywhere**：策略代码派生自 `BaseStrategy`，回测研究、模拟盘推演与实盘交易无缝切换，无需修改一行交易决策逻辑；
- **全要素交易摩擦保真**：
  - 印花税：A 股股票卖出单向征收万 5（ETF 与基金免征）；
  - 佣金：双向征收万 2.5，设置最低 5 元起征门槛；
  - 滑点模型：买入成交价上浮，卖出成交价下浮；
  - 交易限制：严格执行 100 股整手交易限制与涨跌停无法买卖规则；
- **T+1 制度结算**：当日买入资产处于锁定状态不可卖出，闭市后调用 `settle_day_end()` 统一解锁进入次日可用持仓。

---

### 2.4 行情与特征数据底座 (`packages/stock-data`)

- **绝对无状态中台**：仅负责数据的采集、清洗、除权复权、聚合供给，不掺杂任何交易策略逻辑；
- **多数据源智能熔断降级**：
  - 优先主通道：TuShare Pro 专业数据接口；
  - 备用自动降级通道：AkShare / 新浪财经公开实时接口；
  - 本地缓存通道：DuckDB + Parquet 列式存储，毫秒级零拷贝读取；
- **严格 Point-in-Time 时序切片**：确保历史回测中的任何截面数据仅包含当时已知事实，彻底杜绝未来函数偏差。

---

### 2.5 前端智能量化控制台 (`apps/web-admin`)

- **技术栈**：Vue 3 + Vite + TypeScript + Pinia + ECharts；
- **视觉设计规范**：深色玻璃拟态（Dark Glassmorphism），Tailored HSL 色彩体系，流动渐变与呼吸微动效；
- **核心功能模块**：
  - **策略工作台（Strategy Workbench）**：内置 Monaco Code Editor 代码编辑器，支持 Python 量化策略在线编写、智能关键字与因子自动补全、策略热生效；
  - **回测分析仪表盘（Backtest Dashboard）**：动态渲染基准对比收益曲线、每日净值、动态回撤面积图、持仓变动与成交流水明细；
  - **智能体人机协同对话面板（Agent Copilot）**：支持自然语言量化交互、全量工具调用过程可视化呈现、审批卡片交互。

---

## 三、 网络拓扑与生产环境部署 (Production Topology)

系统已在生产服务器 `43.155.186.45` 部署上线，采用 Nginx 作为单点网关，全微服务统一编排：

```mermaid
flowchart TD
    Internet["互联网流量 / 外部客户端<br/>(浏览器 Web / Claude CLI / SDK)"] --> Nginx["生产 Nginx 单一接入网关 (Port 80)"]

    subgraph ReverseProxyRules["Nginx 反向代理分流映射"]
        Nginx -->|"/"| WebAdmin["apps/web-admin (Port 3000)<br/>前端静态资源与单页应用"]
        Nginx -->|"/api/v1/quant/"| SQuant["services/quant-server (Port 8080)<br/>量化策略与回测引擎"]
        Nginx -->|"/api/v1/agent/"| SAgent["services/quant-agent (Port 8090)<br/>专家智能体与自治工具"]
        Nginx -->|"/api/v1/auth/"| SCommon["services/common-server (Port 8000)<br/>用户认证与权限网关"]
        Nginx -->|"/v1/ & /messages & /api/v1/ai/"| AICore["packages/ai-core (Port 8070)<br/>无状态双引擎算力网关"]
    end

    subgraph HostMounts["Docker 容器与宿主机资源共享"]
        AICore -. "只读挂载宿主机二进制与认证" .-> HostBin["宿主机 /root/.gemini & node 工具链"]
        AICore -. "容器内 Overlayfs 可写层" .-> Sandbox["/tmp/quant_ai_clean_sandbox (纯净沙箱)"]
    end
```

### 端口与路由一览表

| 访问路由前缀 | 内部后端服务 | 宿主监听端口 | 协议标准 | 核心用途 |
| :--- | :--- | :--- | :--- | :--- |
| `/` | `web-admin` | `3000` | HTTP / HTML5 | 桌面看盘看板与策略工作台前端界面 |
| `/api/v1/quant/` | `quant-server` | `8080` | RESTful JSON | 策略元数据提取、在线回测、KPI 指标计算 |
| `/api/v1/agent/` | `quant-agent` | `8090` | SSE / RESTful | 量化专家 Agent 对话、工具调用、人在回路审批 |
| `/api/v1/auth/` | `common-server` | `8000` | RESTful JSON | 统一用户注册、密码加盐校验、JWT Token 颁发 |
| `/v1/` | `ai-core` | `8070` | OpenAI 协议 | OpenAI 格式的模型问答与模型矩阵列表 |
| `/messages` | `ai-core` | `8070` | Anthropic 协议 | 供 Claude CLI / Anthropic SDK 直连使用 |
| `/api/v1/ai/` | `ai-core` | `8070` | RESTful JSON | 量化系统内部 Agent 专用算力接口与探活 |

---

## 四、 高可用、安全与 SRE 运维规范

1. **固定安全鉴权机制**：
   - 算力网关强制校验 `Authorization: Bearer sk-quant-agy-8f92e10c74b6` 或 `x-api-key: sk-quant-agy-8f92e10c74b6`，非授权请求直接 401 拦截；
2. **故障隔离与自愈**：
   - 预热待命池单个子进程异常退出不影响整个微服务，池控制器自动补位；
   - 客户端断开连接（如按 `Ctrl+C`）即时向子进程发送 `SIGTERM/SIGKILL`，杜绝孤儿进程与内存泄漏；
3. **资源开销与 Scale-to-Zero 平衡**：
   - 活跃状态：4 个预热待命进程稳定占用约 640MB 内存，CPU 错峰拉起平滑稳定；
   - 闲置状态：5 分钟无调用自动销毁全部待命进程，内存即刻释放归零。
