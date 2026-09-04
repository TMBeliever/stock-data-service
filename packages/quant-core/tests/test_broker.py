from quant_core.core.models import Order, Portfolio, OrderSide, OrderStatus
from quant_core.backtest.broker import SimulatedBroker

def test_broker_buy_with_min_commission():
    broker = SimulatedBroker(
        slippage_pct=0.001,
        commission_rate=0.00025,
        min_commission=5.0,
        stamp_tax_rate=0.0005,
        t_plus_one=True
    )
    portfolio = Portfolio(initial_cash=50_000.0, cash=50_000.0)
    
    order = Order(
        order_id="ord1", symbol="600000.SH.STK", side=OrderSide.BUY,
        quantity=100.0, created_at=1000, updated_at=1000
    )
    trade = broker.match_order(order, current_price=10.0, portfolio=portfolio, timestamp=1000)
    
    assert trade is not None
    assert trade.commission == 5.0  # 最低 5 元
    assert trade.tax == 0.0         # 买入无印花税
    assert trade.price == 10.0 * 1.001  # 上滑点
    assert order.status == OrderStatus.FILLED
    assert portfolio.get_position("600000.SH.STK").quantity == 100.0

def test_broker_sell_stamp_tax():
    broker = SimulatedBroker(
        slippage_pct=0.0,
        commission_rate=0.00025,
        min_commission=5.0,
        stamp_tax_rate=0.0005,
        t_plus_one=False
    )
    portfolio = Portfolio(initial_cash=50_000.0, cash=10_000.0)
    pos = portfolio.get_position("600519.SH.STK")
    pos.quantity = 100.0
    pos.available_quantity = 100.0
    pos.avg_cost = 1000.0
    
    order = Order(
        order_id="ord2", symbol="600519.SH.STK", side=OrderSide.SELL,
        quantity=100.0, created_at=2000, updated_at=2000
    )
    trade = broker.match_order(order, current_price=1000.0, portfolio=portfolio, timestamp=2000)
    
    assert trade is not None
    assert trade.tax == 50.0        # 印花税万5
    assert trade.commission == 25.0 # 佣金 25 元
    assert pos.quantity == 0.0
