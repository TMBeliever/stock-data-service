# Quant Core SDK (`packages/quant-core`)

高内聚、轻量级、面向 A 股与全球资产的量化交易核心引擎、通用因子库与模拟撮合底座。

---

## 核心功能模块

### 1. 通用量化因子库 (`quant_core.factors`)
内置基于向量化与滑动切片计算的常用量化指标：
* **技术指标 (`technical`)**：`sma`, `ema`, `rsi`, `macd`, `bollinger_bands`, `atr`
* **动量指标 (`momentum`)**：`roc` (收益率变动百分比), `momentum` (价格变动差值)
* **估值与截面 (`value`)**：`percentile_rank` (历史分位数), `zscore` (标准化得分)

### 2. 仿真撮合器 (`quant_core.backtest.broker.SimulatedBroker`)
* **A 股 T+1 交易制度**：买入锁定当日可用持仓，次日结算解锁；
* **真实摩擦成本**：
  * 印花税：卖出单向万五（ETF / 指数免征）；
  * 佣金：双向万二点五，最低 5 元起征；
  * 滑点模型：固定百分比滑点调整成交价格，避免在成本计算中重复计提。

### 3. 事件驱动回测引擎 (`quant_core.backtest.engine.BacktestEngine`)
* **时序推进**：毫秒级时间戳推进，支持全宇宙多标的对齐；
* **无前视偏差**：策略决策在收到行情后发出，次日开盘或严格按时序撮合；
* **日终清算与净值打点**：在每个交易日最后一根切片精确结算 T+1 并沉淀每日资产快照。

### 4. 绩效指标统计体系 (`quant_core.backtest.metrics.PerformanceAnalytics`)
* 年化收益率 (CAGR)、最大回撤 (Max Drawdown)、夏普比率 (Sharpe Ratio)、索提诺比率 (Sortino Ratio)、卡玛比率 (Calmar Ratio)；
* **真实胜率与盈亏比**：基于成交流水 FIFO 配对（Round-trip Trade）精准计算实际盈亏。

---

## 快速使用

```python
from quant_core.core.models import Bar
from quant_core.backtest.broker import SimulatedBroker
from quant_core.backtest.engine import BacktestEngine
from quant_core.strategies.moving_average_cross import DualMovingAverageStrategy

# 1. 实例化策略与撮合器
strategy = DualMovingAverageStrategy(fast_period=5, slow_period=20)
broker = SimulatedBroker(t_plus_one=True)

# 2. 运行回测
engine = BacktestEngine(strategy=strategy, broker=broker, initial_cash=100_000.0)
result = engine.run({"510300.SH.ETF": bars})

# 3. 输出绩效分析
result.print_summary()
```

## 运行单元测试
```bash
uv run pytest packages/quant-core/tests -v
```
