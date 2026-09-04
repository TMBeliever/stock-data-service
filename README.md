# Global Quant Strategy & Execution System (量化策略与交易执行系统底座)

高内聚、轻量、高性能的事件驱动与向量化量化交易底座，原生深度对接 `stock-data` 全球数据中台。

---

## 核心特色
1. **双模极速数据直通 (Dual-Mode Data Client)**：
   - **Zero-Copy SDK 模式**：同机或共享只读挂载环境下直接调用 DuckDB/Polars 零拷贝读取本地 Parquet，回测速度提升 50 倍以上；
   - **REST/WebSocket 模式**：容器化或跨机器网络下自动降级为 HTTP 请求与 WebSocket 实时流订阅。
2. **工业级模拟撮合 (Simulated Exchange Broker)**：
   - 原生支持 **A 股 T+1 交易制度**（当日买入可用锁定，次日解锁）；
   - 精确计算 **A 股印花税**（卖出单向万五，ETF/指数免征）、**佣金**（万二点五，最低 5 元起征）与 **滑点模型**；
   - 支持买入整手限制（一手 100 股，卖出可零股）。
3. **标准化策略生命周期 (Lifecycle Hooks)**：
   - `on_init()`, `on_start()`, `on_bar()`, `on_snapshot()`, `on_order_update()`, `on_trade()`, `on_stop()`；
   - 内置强大的资金与目标仓位调仓助手（如 `order_target_percent(symbol, 0.8)`）。
4. **全套量化绩效评价体系 (Performance Metrics)**：
   - 自动统计年化收益率 (CAGR)、最大回撤 (Max Drawdown)、夏普比率 (Sharpe Ratio)、索提诺比率 (Sortino Ratio)、卡玛比率 (Calmar Ratio)、胜率与盈亏比。

---

## 快速使用

### 1. 运行内置策略回测
```bash
# 运行双均线趋势策略 (MA5 / MA20) 回测沪深300 ETF
python run_backtest.py --symbol 510300.SH.ETF --strategy ma --start 2022-01-01 --end 2024-01-01

# 运行红利低波动态估值定投策略
python run_backtest.py --symbol 512890.SH.ETF --strategy dividend --start 2021-01-01 --end 2024-01-01
```

### 2. 运行全量单元测试
```bash
pytest tests -v
```

### 3. 与 stock-data 多服务 Docker Compose 联动
在当前系统的 `docker-compose.yml` 中直接挂载共享数据卷，即可享受跨容器的隔离安全与极速读取。
