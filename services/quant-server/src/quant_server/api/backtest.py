import datetime
from typing import Optional, Dict, Any
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from quant_core.client.data_client import data_client
from quant_core.backtest.broker import SimulatedBroker
from quant_core.backtest.engine import BacktestEngine
from quant_core.strategies.moving_average_cross import DualMovingAverageStrategy
from quant_core.strategies.dividend_etf_rebalance import DividendETFRebalanceStrategy
from quant_core.strategies.dividend_dca import SmartDividendDCAStrategy
from quant_core.strategies.buy_and_hold import BuyAndHoldStrategy
from quant_core.strategies.extreme_dip_heavy import ExtremeDipHeavyStrategy
from quant_core.strategies.dynamic_rebalance import DynamicRebalanceStrategy

router = APIRouter()

class BacktestRequest(BaseModel):
    symbol: str = Field(default="510300.SH.ETF", description="回测标的代码")
    strategy: str = Field(default="dca", description="策略类型: dca, all_in, ma, dividend, dip_heavy, rebalance")
    start: str = Field(default="2021-01-01", description="开始日期 YYYY-MM-DD")
    end: Optional[str] = Field(default=None, description="结束日期 YYYY-MM-DD (留空为最新日)")
    initial_cash: float = Field(default=100_000.0, description="初始资金 (CNY)")
    params: Optional[Dict[str, Any]] = Field(default=None, description="自定义策略参数")

@router.post("/backtest/run")
def run_backtest_endpoint(req: BacktestRequest):
    """在线运行策略回测并返回标准绩效与每日净值曲线"""
    # 1. 获取行情数据
    bars = data_client.get_bars(symbol=req.symbol, period="1d", start=req.start, end=req.end, adjust="qfq")
    if not bars:
        raise HTTPException(status_code=404, detail=f"No K-line data found for {req.symbol}")

    # 2. 构造策略实例
    if req.strategy == "ma":
        fast = req.params.get("fast_period", 5) if req.params else 5
        slow = req.params.get("slow_period", 20) if req.params else 20
        strat = DualMovingAverageStrategy(fast_period=fast, slow_period=slow)
    elif req.strategy == "dividend":
        win = req.params.get("window", 120) if req.params else 120
        strat = DividendETFRebalanceStrategy(window=win)
    elif req.strategy == "dca":
        base_amt = req.params.get("base_amount", 1000.0) if req.params else 1000.0
        win = req.params.get("window", 250) if req.params else 250
        strat = SmartDividendDCAStrategy(base_amount=base_amt, window=win, enable_take_profit=True)
    elif req.strategy in ("all_in", "buy_and_hold"):
        target_pct = req.params.get("target_pct", 0.99) if req.params else 0.99
        strat = BuyAndHoldStrategy(target_pct=target_pct)
    elif req.strategy in ("dip_heavy", "extreme_dip"):
        one_s = req.params.get("one_shot", True) if req.params else True
        dip_t = req.params.get("dip_threshold", 0.20) if req.params else 0.20
        ma_p = req.params.get("ma_period", 120) if req.params else 120
        def_pct = req.params.get("defensive_pct", 0.20) if req.params else 0.20
        strat = ExtremeDipHeavyStrategy(dip_threshold=dip_t, one_shot=one_s, ma_period=ma_p, defensive_pct=def_pct)
    elif req.strategy in ("rebalance", "dynamic_rebalance"):
        tgt = req.params.get("target_pct", 0.85) if req.params else 0.85
        band = req.params.get("rebalance_band", 0.05) if req.params else 0.05
        chk = req.params.get("check_interval", 5) if req.params else 5
        strat = DynamicRebalanceStrategy(target_pct=tgt, rebalance_band=band, check_interval=chk)
    else:
        raise HTTPException(status_code=400, detail=f"Unknown strategy: {req.strategy}")

    # 3. 构造撮合器 (万0.8 免5, ETF免印花税)
    broker = SimulatedBroker(
        slippage_pct=0.0005,
        commission_rate=0.00008,
        min_commission=0.0,
        stamp_tax_rate=0.0,
        t_plus_one=True
    )
    engine = BacktestEngine(strategy=strat, broker=broker, initial_cash=req.initial_cash)

    # 4. 执行回测
    result = engine.run({req.symbol: bars})

    benchmark_records = [
        {
            "date": b.date_str,
            "timestamp": b.timestamp,
            "close": b.close,
            "return_pct": round((b.close - bars[0].close) / bars[0].close, 6) if bars[0].close > 0 else 0.0
        }
        for b in bars
    ]

    return {
        "summary": {
            "initial_cash": result.initial_cash,
            "final_equity": result.final_equity,
            "total_return": result.total_return,
            "annualized_return": result.annualized_return,
            "max_drawdown": result.max_drawdown,
            "sharpe_ratio": result.sharpe_ratio,
            "sortino_ratio": result.sortino_ratio,
            "calmar_ratio": result.calmar_ratio,
            "win_rate": result.win_rate,
            "profit_factor": result.profit_factor,
            "total_trades": result.total_trades,
        },
        "daily_records": result.daily_records,
        "benchmark_records": benchmark_records,
        "trades": [
            {
                "trade_id": t.trade_id,
                "symbol": t.symbol,
                "side": t.side.value if hasattr(t.side, "value") else str(t.side),
                "price": t.price,
                "quantity": t.quantity,
                "commission": round(t.commission, 4),
                "timestamp": t.timestamp,
                "datetime_str": datetime.datetime.fromtimestamp(t.timestamp / 1000).strftime("%Y-%m-%d %H:%M:%S") if t.timestamp else "",
            }
            for t in engine.portfolio.trades
        ]
    }


class CustomBacktestRequest(BaseModel):
    symbol: str = Field(default="510300.SH.ETF", description="回测标的代码")
    code: str = Field(..., description="用户自定义 Python 策略源码")
    start: str = Field(default="2021-01-01", description="开始日期 YYYY-MM-DD")
    end: Optional[str] = Field(default=None, description="结束日期 YYYY-MM-DD (留空为最新日)")
    initial_cash: float = Field(default=100_000.0, description="初始资金 (CNY)")


@router.post("/backtest/run-custom")
def run_custom_backtest_endpoint(req: CustomBacktestRequest):
    """通过安全 AST 沙箱执行用户自定义 Python 策略源码并返回回测绩效与净值数据"""
    from quant_server.api.sandbox import StrategyCodeSandbox, SecurityCheckError

    # 1. 语法树审计与策略类动态加载
    try:
        strategy_cls = StrategyCodeSandbox.load_strategy_class(req.code)
        strat = strategy_cls()
    except SecurityCheckError as e:
        raise HTTPException(status_code=400, detail=f"安全策略拦截: {str(e)}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"代码结构错误: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"策略编译/初始化失败: {str(e)}")

    # 2. 获取行情数据
    bars = data_client.get_bars(symbol=req.symbol, period="1d", start=req.start, end=req.end, adjust="qfq")
    if not bars:
        raise HTTPException(status_code=404, detail=f"未找到标的 {req.symbol} 在指定时间区间的行情数据")

    # 3. 构造撮合器并运行
    broker = SimulatedBroker(
        slippage_pct=0.0005,
        commission_rate=0.00008,
        min_commission=0.0,
        stamp_tax_rate=0.0,
        t_plus_one=True
    )
    engine = BacktestEngine(strategy=strat, broker=broker, initial_cash=req.initial_cash)

    try:
        result = engine.run({req.symbol: bars})
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"回测运行时异常: {str(e)}")

    benchmark_records = [
        {
            "date": b.date_str,
            "timestamp": b.timestamp,
            "close": b.close,
            "return_pct": round((b.close - bars[0].close) / bars[0].close, 6) if bars[0].close > 0 else 0.0
        }
        for b in bars
    ]

    return {
        "summary": {
            "initial_cash": result.initial_cash,
            "final_equity": result.final_equity,
            "total_return": result.total_return,
            "annualized_return": result.annualized_return,
            "max_drawdown": result.max_drawdown,
            "sharpe_ratio": result.sharpe_ratio,
            "sortino_ratio": result.sortino_ratio,
            "calmar_ratio": result.calmar_ratio,
            "win_rate": result.win_rate,
            "profit_factor": result.profit_factor,
            "total_trades": result.total_trades,
        },
        "daily_records": result.daily_records,
        "benchmark_records": benchmark_records,
        "trades": [
            {
                "trade_id": t.trade_id,
                "symbol": t.symbol,
                "side": t.side.value if hasattr(t.side, "value") else str(t.side),
                "price": t.price,
                "quantity": t.quantity,
                "commission": round(t.commission, 4),
                "timestamp": t.timestamp,
                "datetime_str": datetime.datetime.fromtimestamp(t.timestamp / 1000).strftime("%Y-%m-%d %H:%M:%S") if t.timestamp else "",
            }
            for t in engine.portfolio.trades
        ]
    }

