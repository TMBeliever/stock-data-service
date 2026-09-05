from quant_core.core.models import Bar
from quant_core.backtest.engine import BacktestEngine
from quant_core.backtest.broker import SimulatedBroker
from quant_core.strategies.all_weather import AllWeatherStrategy

def test_all_weather_strategy_backtest():
    """验证达利欧全天候策略回测逻辑与动态再平衡机制"""
    bars = []
    base_ts = 1609459200000  # 2021-01-01
    day_ms = 86400000
    # 模拟 60 个交易日的多变行情
    prices = [4.0 + (i % 10) * 0.1 for i in range(60)]
    for idx, p in enumerate(prices):
        bars.append(Bar(
            symbol="510300.SH.ETF",
            timestamp=base_ts + idx * day_ms,
            open=p - 0.02,
            high=p + 0.05,
            low=p - 0.05,
            close=p,
            volume=50000.0
        ))

    strategy = AllWeatherStrategy(stock_weight=0.30, rebalance_band=0.03, rebalance_interval=10)
    broker = SimulatedBroker(slippage_pct=0.0, commission_rate=0.0003, min_commission=5.0, t_plus_one=False)
    engine = BacktestEngine(strategy=strategy, broker=broker, initial_cash=200_000.0)

    result = engine.run({"510300.SH.ETF": bars})

    assert result.total_trades > 0
    assert result.final_equity > 0
    assert result.total_return != 0.0
