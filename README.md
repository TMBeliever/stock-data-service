# Global Quant System (全栈量化工程 Monorepo)

基于现代现代化工具链打造的 **Polyglot Monorepo（多语言统一工作区）** 全栈量化投研与执行系统。  
系统涵盖：**全球数据中台 (`stock-data`)**、**量化投研内核与通用因子库 (`quant-core`)**、**控制面 API 服务 (`quant-server`)** 以及 **前端/移动跨端看盘看板 (`web-admin`)**。

---

## 架构拓扑图

```mermaid
flowchart TD
    subgraph DataPlatform["1. 数据底座 (packages/stock-data)"]
        SD_Adapters["数据采集器 (AkShare / YahooFinance)"]
        SD_Storage["存储引擎 (DuckDB + 本地 Parquet)"]
        SD_Service["数据服务网关 (FastAPI / 端口: 8000)"]
        SD_Adapters --> SD_Storage --> SD_Service
    end

    subgraph QuantCore["2. 量化内核 SDK (packages/quant-core)"]
        QC_Factors["通用因子库 (SMA, RSI, MACD, BOLL, ATR, 动量)"]
        QC_Broker["撮合引擎 (Next-Open撮合, A股 T+1, 印花税, 滑点)"]
        QC_Engine["事件驱动回测引擎 (BacktestEngine, PerformanceMetrics)"]
        QC_Benchmark["基准策略库 (DualMA, DividendRebalance)"]
    end

    subgraph ServiceApp["3. 服务控制面 (apps/quant-server)"]
        QS_API["FastAPI 异步网关 (端口: 8080)"]
        QS_Backtest["在线回测调度 & 每日净值曲线输出"]
        QS_Strategies["策略管理与自描述参数 Schema"]
        QS_API --> QS_Backtest
        QS_API --> QS_Strategies
    end

    subgraph Clients["4. 客户端与看板应用 (apps/*)"]
        Client_Web["web-admin: Vue 3 + Vite + ECharts 看板"]
        Client_Mobile["移动小程序 / Swift iOS 原生 App (预备扩展)"]
    end

    SD_Service -->|"行情流 / Parquet 零拷贝直读"| QuantCore
    QuantCore -->|"本地 Editable 依赖"| ServiceApp
    ServiceApp -->|"REST API / WebSocket"| Clients
```

---

## 模块结构清单

| 路径 | 模块类型 | 技术栈 | 核心定位与职责 |
| :--- | :--- | :--- | :--- |
| **`packages/stock-data`** | 核心数据包 | Python / DuckDB / Polars / FastAPI | 全球资产(A股/美股/ETF)数据抓取、除权降水因子清洗、毫秒级 Parquet 存储与行情网关。 |
| **`packages/quant-core`** | 核心内核 SDK | Python / Polars / NumPy / Pydantic | 标准量化内核底座：内置通用因子库、模拟真实交易所撮合、A股制度模拟与绩效统计报表。 |
| **`apps/quant-server`** | 服务应用 | Python / FastAPI / Uvicorn | 量化平台后端中枢：对外暴露在线回测、策略自描述元数据查询与账户状态接口。 |
| **`apps/web-admin`** | 前端应用 | Vue 3 / Vite / TypeScript / ECharts | 桌面端量化投资看板：策略参数配置、回测收益曲线可视化与风控预警展示。 |
| **`docs/`** | 架构与开发文档 | Markdown | 包含深度架构设计规范、开发实战手册与多端对接规范。 |

---

## 快速上手与本地开发

本项目采用 **Python `uv workspace`** 与 **前端 `pnpm workspace`** 双工作区治理。

### 1. 环境准备
确保机器已安装 `uv`（推荐）和 `pnpm`：
```bash
# 安装依赖并一键建立全工作区本地软链接
uv sync --all-packages
```

### 2. 运行命令行离线回测
无需启动任何服务，直接在终端回测内置基准策略：
```bash
# 运行双均线趋势策略 (MA5 / MA20) 回测沪深 300 ETF
uv run python run_backtest.py --symbol 510300.SH.ETF --strategy ma --start 2022-01-01 --end 2024-01-01

# 运行红利低波动态估值定投策略
uv run python run_backtest.py --symbol 512890.SH.ETF --strategy dividend
```

### 3. 分模块本地开发启动 (毫秒级热重载)
你在 `packages/quant-core` 中修改任何因子或撮合代码，所有上层服务都会自动热生效：
```bash
# 终端 1: 启动底层数据中台 (端口: 8000)
pnpm dev:data
# 访问: http://localhost:8000/docs

# 终端 2: 启动量化服务中枢 (端口: 8080)
pnpm dev:server
# 访问: http://localhost:8080/docs
```

### 4. 运行单元测试
```bash
# 运行量化内核全部单测 (撮合规则、T+1、因子计算、回测指标)
pnpm test:core

# 运行数据中台离线单测
pnpm test:data
```

### 5. Docker Compose 全栈容器化启动
```bash
docker compose up -d --build
```
自动拉起 `stock-data-service` 与 `quant-server-service` 并配置容器间内网直通。

---

## 深入文档指南

* 📐 **[系统架构设计规范 (docs/architecture.md)](docs/architecture.md)**：深入了解三层架构解耦、交易流水线、无未来函数撮合设计与跨端 (Vue/Swift) 对接协议。
* 🛠️ **[开发与贡献手册 (docs/dev-guide.md)](docs/dev-guide.md)**：如何编写新因子、如何开发新策略、如何新增 API 接口。
