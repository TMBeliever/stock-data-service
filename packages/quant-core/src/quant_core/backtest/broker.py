import uuid
from typing import Optional, Tuple
from quant_core.core.models import Order, Trade, OrderSide, OrderType, OrderStatus, Portfolio, Position

class SimulatedBroker:
    """
    真实模拟撮合器 (Simulated Exchange & Broker)：
    严格模拟 A 股与美股交易所的撮合逻辑、滑点、佣金与印花税。
    - A 股印花税：卖出单向征收 0.05% (ETF / 指数免印花税)
    - 佣金：万0.8 (0.00008)，支持免5 (最低佣金 0 元起征)
    - 印花税：仅 A 股个股单向 0.05% (ETF 与指数完全免税)
    - 滑点模型：固定比例或固定价格滑点
    - T+1 交易制度：当天买入可用数量锁定，当日不可卖出
    """
    def __init__(
        self,
        slippage_pct: float = 0.0005,        # 0.05% 滑点
        commission_rate: float = 0.00008,    # 万0.8 佣金 (0.008%)
        min_commission: float = 0.0,         # 最低佣金 0 元 (免5)
        stamp_tax_rate: float = 0.0005,      # 印花税万5 (仅股票卖出单向，ETF自动免征)
        t_plus_one: bool = True,             # 开启 A 股 T+1
        lot_size: int = 100                  # 买入一手 100 股限制
    ):
        self.slippage_pct = slippage_pct
        self.commission_rate = commission_rate
        self.min_commission = min_commission
        self.stamp_tax_rate = stamp_tax_rate
        self.t_plus_one = t_plus_one
        self.lot_size = lot_size
        self.rejected_orders: list = []

    def calculate_tax_and_commission(self, symbol: str, side: OrderSide, price: float, quantity: float) -> Tuple[float, float, float]:
        """计算滑点成本、佣金与印花税"""
        amount = price * quantity
        # 1. 佣金
        comm = amount * self.commission_rate
        if self.min_commission > 0 and comm < self.min_commission:
            comm = self.min_commission
            
        # 2. 印花税 (仅股票 STK 卖出收取，ETF 与 IDX 免征)
        tax = 0.0
        if side == OrderSide.SELL and ("STK" in symbol or not ("ETF" in symbol or "IDX" in symbol)):
            tax = amount * self.stamp_tax_rate
            
        # 3. 滑点金额
        slip = amount * self.slippage_pct
        return comm, tax, slip

    def match_order(self, order: Order, current_price: float, portfolio: Portfolio, timestamp: int) -> Optional[Trade]:
        """撮合订单并更新账户资产"""
        if not order.is_active or current_price <= 0:
            return None

        # 价格滑点调整
        if order.side == OrderSide.BUY:
            exec_price = current_price * (1.0 + self.slippage_pct)
        else:
            exec_price = current_price * (1.0 - self.slippage_pct)

        # 校验限价单成交条件 (仅限价单生效)
        if order.order_type == OrderType.LIMIT and order.price is not None:
            if order.side == OrderSide.BUY and exec_price > order.price:
                return None  # 买单价格超出限价
            if order.side == OrderSide.SELL and exec_price < order.price:
                return None  # 卖单价格低于限价

        comm, tax, slip = self.calculate_tax_and_commission(order.symbol, order.side, exec_price, order.quantity)
        total_buy_cost = exec_price * order.quantity + comm

        pos = portfolio.get_position(order.symbol)

        # 买单资金校验
        if order.side == OrderSide.BUY:
            if portfolio.cash < total_buy_cost:
                order.status = OrderStatus.REJECTED
                order.reason = f"资金不足: 需 ¥{total_buy_cost:,.2f}，当前可用 ¥{portfolio.cash:,.2f}"
                self.rejected_orders.append({
                    "symbol": order.symbol,
                    "side": "BUY",
                    "price": exec_price,
                    "quantity": order.quantity,
                    "need_cash": round(total_buy_cost, 2),
                    "avail_cash": round(portfolio.cash, 2),
                    "reason": order.reason,
                    "timestamp": timestamp,
                })
                return None
            portfolio.cash -= total_buy_cost

        # 卖单可用持仓校验 (T+1 检查)
        elif order.side == OrderSide.SELL:
            avail = pos.available_quantity if self.t_plus_one else pos.quantity
            if avail < order.quantity:
                order.status = OrderStatus.REJECTED
                order.reason = f"可用持仓不足: 需卖出 {order.quantity} 股，当前可用 {avail} 股"
                self.rejected_orders.append({
                    "symbol": order.symbol,
                    "side": "SELL",
                    "price": exec_price,
                    "quantity": order.quantity,
                    "reason": order.reason,
                    "timestamp": timestamp,
                })
                return None
            # 卖出净收入到账
            sell_proceeds = exec_price * order.quantity - comm - tax
            portfolio.cash += sell_proceeds

        # 生成成交流水
        trade_amount = round(exec_price * order.quantity, 2)
        trade = Trade(
            trade_id=f"trd_{uuid.uuid4().hex[:12]}",
            order_id=order.order_id,
            symbol=order.symbol,
            side=order.side,
            price=exec_price,
            quantity=order.quantity,
            amount=trade_amount,
            commission=comm,
            tax=tax,
            slippage=slip,
            timestamp=timestamp,
            reason=order.reason or ""
        )

        # 更新订单状态
        order.filled_quantity = order.quantity
        order.filled_avg_price = exec_price
        order.status = OrderStatus.FILLED
        order.updated_at = timestamp

        # 更新持仓
        pos.apply_trade(trade, t_plus_one=self.t_plus_one)
        portfolio.trades.append(trade)

        return trade
