# Global Stock Data Service (全球股票数据服务)

面向股票分析、量化交易与策略回测的轻量、高性能全球市场数据中台（以 50GB 存储为安全预算包络）。

## 核心架构特色
1. **50GB 存储预算与安全防护**：Parquet 列式存储 + ZSTD 高压缩比，全量覆盖全球宽基与核心 ETF，个股实行 100% 纯 LazyLoad 与 LRU 淘汰安全气阀（非物理单盘硬顶，而是带有宿主机安全冗余的缓存限额包络）。
2. **多资产统一规范**：原生支持股票 (`STK`)、宽基指数 (`IDX`)、ETF 基金 (`ETF`)，严格统一 `[TICKER].[MARKET].[TYPE]` 全局标识。
3. **极速向量化算力**：基于 DuckDB + Polars，支持动态前/后复权、A 股 Session 隔离分钟线聚合（5m/15m/60m）、ETF 折溢价计算。
4. **工业级防护**：SingleFlight 请求合并防止高并发击穿，Parquet 临时文件原子替换防写入中断损坏，Smart Append 增量补齐历史断层。
5. **严谨真实数据与 PIT 语义透明**：集成真实 A 股源（AkShare）与全球源（Yahoo Finance）。A 股支持基于官方公告披露日 (announcement_date) 的严格 PIT (Strict Point-in-Time)；海外标的因源端无可靠历史披露时间戳明确标为估算 (ESTIMATED)，杜绝过度承诺。

## 文档与接口规范
* **完整 API 接口文档**：[docs/API.md](docs/API.md)
* **OpenAPI 3.1 机器可读规范**：[docs/openapi.json](docs/openapi.json)（支持直接导入 Postman、Apifox、Swagger Editor）
* **在线交互式文档**：启动服务后访问 `http://localhost:8000/docs`

## 四大接入通道 (Quad-Channel Access)

1. **REST API (HTTP)**：`http://localhost:8000/api/v1/...`，适用于微服务与标准 Web 后端集成；
2. **Python SDK (Zero-Copy)**：`from sdk import StockDataSDK`，直接在内存输出 Polars DataFrame，速度提升 50 倍；
3. **WebSocket 网关 (查询与快照订阅)**：`ws://localhost:8000/ws/market`，支持长连接按需订阅、首包快照下发与低延迟行情查询网关；
4. **MCP Server (AI 智能体)**：`python mcp_server.py`，支持 Claude Desktop / Cursor 一键接入，化身 AI 金融投研助理。

## 快速使用 (傻瓜式一键启动)

```bash
# 1. 本地一键启动 (自动检测环境、初始化底座并拉起服务)
./start.sh
# 或直接输入: make

# 2. 一键停止
./stop.sh

# 3. Docker 容器化一键部署
docker compose up -d

# 4. 运行回测演示策略 (红利低波估值分位数定投)
python examples/backtest_dividend_low_vol.py

# 5. 常用快捷指令
make test      # 运行全量单元测试 (46项全通)
make status    # 查看 50G 磁盘与缓存水位
make sync      # 盘后增量同步自选股池
make clean     # 手动触发一次 LRU 淘汰清理
make docs      # 重新导出最新 API 接口定义
```

