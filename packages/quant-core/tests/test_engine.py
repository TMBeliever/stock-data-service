from quant_core.core.models import Bar
from quant_core.backtest.engine import BacktestEngine
from quant_core.backtest.broker import SimulatedBroker
from quant_core.strategies.moving_average_cross import DualMovingAverageStrategy

def test_backtest_engine_run():
    # 构造先跌后涨行情 (触发 MA3 上穿 MA10 形成金叉)
    bars = []
    base_ts = 1609459200000 # 2021-01-01
    day_ms = 86400000
    prices = [20.0 - i * 0.5 for i in range(15)] + [12.5 + i * 0.8 for i in range(25)]
    for idx, p in enumerate(prices):
        bars.append(Bar(
            symbol="510300.SH.ETF",
            timestamp=base_ts + idx * day_ms,
            open=p - 0.1,
            high=p + 0.2,
            low=p - 0.2,
            close=p,
            volume=10000.0
        ))
        
    strat = DualMovingAverageStrategy(fast_period=3, slow_period=10)
    broker = SimulatedBroker(slippage_pct=0.0, commission_rate=0.0, min_commission=0.0, t_plus_one=False)
    engine = BacktestEngine(strategy=strat, broker=broker, initial_cash=100_000.0)
    
    res = engine.run({"510300.SH.ETF": bars})
    
    assert res.total_trades > 0
    assert res.final_equity > res.initial_cash
    assert res.total_return > 0.0
