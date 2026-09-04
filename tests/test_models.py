import pytest
from quant_system.core.models import Order, Trade, Position, Portfolio, OrderSide, OrderStatus

def test_position_pnl_and_t_plus_one():
    pos = Position(symbol="600519.SH.STK")
    
    buy_trade = Trade(
        trade_id="t1", order_id="o1", symbol="600519.SH.STK",
        side=OrderSide.BUY, price=1000.0, quantity=100.0,
        commission=25.0, tax=0.0, slippage=0.0, timestamp=1000
    )
    pos.apply_trade(buy_trade, t_plus_one=True)
    
    assert pos.quantity == 100.0
    assert pos.available_quantity == 0.0  # T+1 锁定不可卖
    assert pos.avg_cost == 1000.25
    
    # 日终结算
    pos.settle_day_end()
    assert pos.available_quantity == 100.0  # 次日解锁
    
    pos.update_price(1100.0)
    assert pos.market_value == 110_000.0
    assert pos.unrealized_pnl == pytest.approx((1100 - 1000.25) * 100, 0.01)

def test_portfolio_equity_calculation():
    portfolio = Portfolio(initial_cash=100_000.0, cash=50_000.0)
    pos = portfolio.get_position("510300.SH.ETF")
    pos.quantity = 10_000.0
    pos.current_price = 4.0
    
    assert portfolio.total_market_value == 40_000.0
    assert portfolio.total_equity == 90_000.0
    assert portfolio.total_pnl == -10_000.0
    assert portfolio.total_return == -0.10
