# 量化开发与贡献实战手册 (Developer Guide)

本文档面向策略研究员与全栈开发者，介绍如何在 Monorepo 中新增因子、编写策略、扩展服务端 API 以及接入新应用。

---

## 一、 如何新增一个通用量化因子？

所有通用技术指标和量化因子均维护在 `packages/quant-core/src/quant_core/factors/` 目录下。

### 1. 编写因子计算函数
因子函数必须是**纯函数（Pure Function）**，无副作用，输入行情或特征序列，输出浮点数或元组。

例如在 `packages/quant-core/src/quant_core/factors/technical.py` 中增加威廉指标（Williams %R）：
```python
from typing import Sequence

def williams_r(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], period: int = 14) -> float:
    """威廉指标 (Williams %R, -100 ~ 0)"""
    if len(closes) < period:
        return -50.0
    highest_h = max(highs[-period:])
    lowest_l = min(lows[-period:])
    if highest_h == lowest_l:
        return -50.0
    wr = (highest_h - closes[-1]) / (highest_h - lowest_l) * -100.0
    return float(wr)
```

### 2. 在 `factors/__init__.py` 中导出并在 `tests/test_factors.py` 补充单元测试
```python
def test_williams_r():
    h = [10, 12, 14, 15]
    l = [8, 9, 10, 11]
    c = [9, 11, 13, 14]
    assert williams_r(h, l, c, period=3) <= 0
```
运行单测验证：
```bash
pnpm test:core
```

---

## 二、 如何编写一个全新的量化策略？

所有策略必须继承 `BaseStrategy`，并实现 `on_bar` 核心回调。

### 1. 创建策略文件
在 `packages/quant-core/src/quant_core/strategies/` 或上层应用中创建你的策略（例如 `rsi_reversal.py`）：

```python
from quant_core.core.base_strategy import BaseStrategy
from quant_core.core.models import Bar
from quant_core.factors.technical import rsi

class RSIReversalStrategy(BaseStrategy):
    """RSI 超买超卖反转策略"""
    def __init__(self, rsi_period: int = 14, oversold: float = 30.0, overbought: float = 70.0):
        super().__init__(
            name="RSIReversal",
            params={"period": rsi_period, "oversold": oversold, "overbought": overbought}
        )
        self.period = rsi_period
        self.oversold = oversold
        self.overbought = overbought

    def on_bar(self, bar: Bar):
        symbol = bar.symbol
        closes = self.context.get_closes(symbol, n=self.period + 5)
        if len(closes) < self.period + 1:
            return

        current_rsi = rsi(closes, period=self.period)
        pos = self.get_position(symbol)

        # 超卖信号：逢低加仓至 80%
        if current_rsi < self.oversold:
            if pos.quantity == 0:
                self.order_target_percent(symbol, 0.8, reason=f"Oversold RSI={current_rsi:.1f}")

        # 超买信号：止盈清仓
        elif current_rsi > self.overbought:
            if pos.available_quantity > 0:
                self.close_position(symbol, reason=f"Overbought RSI={current_rsi:.1f}")
```

### 2. 本地执行回测评估
在 `run_backtest.py` 中引入你的策略类，或者通过命令行直接调用：
```bash
uv run python run_backtest.py --symbol 510300.SH.ETF --strategy rsi
```

---

## 三、 如何在服务端扩展新 API？

服务端位于 `apps/quant-server/`，基于 FastAPI 架构。

### 1. 新建或修改路由
在 `apps/quant-server/src/quant_server/api/` 下新增路由文件，例如 `portfolio.py`：
```python
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()

@router.get("/portfolio/summary")
def get_portfolio_summary():
    return {
        "cash": 50000.0,
        "market_value": 60000.0,
        "total_equity": 110000.0,
        "positions": []
    }
```

### 2. 在 `main.py` 中注册路由
```python
from quant_server.api.portfolio import router as portfolio_router
app.include_router(portfolio_router, prefix="/api/v1", tags=["Portfolio"])
```
启动服务：
```bash
pnpm dev:server
```
打开 `http://localhost:8080/docs` 即可在 Swagger 交互界面中查看并调试新接口。

---

## 四、 如何在 Monorepo 中新增应用或客户端？

如果你要新建一个项目，例如 Uni-app 小程序：

1. 在 `apps/` 目录下初始化新应用：
   ```bash
   cd apps
   # 例如使用 vue-cli 或 uni-app 脚手架创建工程
   pnpm create vite mini-app --template vue-ts
   ```
2. 根目录 `pnpm-workspace.yaml` 已经包含了 `apps/*`，新应用会自动成为工作区一员；
3. 可以通过 `pnpm --filter mini-app <command>` 独立运行或构建该项目。

---

## 五、 依赖管理与常用规范

* **为 Python 工作区添加依赖**：
  * 为内核添加依赖：`uv add polars --package quant-core`
  * 为服务端添加依赖：`uv add redis --package quant-server`
* **更新全工作区软链接**：
  ```bash
  uv sync --all-packages
  ```
* **保持 Git 树整洁**：
  切勿提交任何 `.parquet`、`.duckdb`、`node_modules` 或 `.venv` 文件。提交前建议运行 `git status` 确认。
