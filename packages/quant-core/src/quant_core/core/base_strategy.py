import uuid
from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any
from quant_core.core.models import (
    Bar, Snapshot, Order, Trade, OrderSide, OrderType, OrderStatus, Position
)
from quant_core.core.context import StrategyContext

class BaseStrategy(ABC):
    """
    量化策略抽象基类：
    提供规范完整的生命周期钩子与内置仓位下达助手。
    无论在回测模式还是盘中实盘模式，策略编写逻辑完全一致。
    """
    def __init__(self, name: str = "BaseStrategy", params: Optional[Dict[str, Any]] = None):
        self.name = name
        self.params = params or {}
        self.context: Optional[StrategyContext] = None
        self._pending_orders: List[Order] = []

    def set_context(self, context: StrategyContext):
        self.context = context

    # -------------------------------------------------------------
    # 策略核心生命周期钩子 (Lifecycle Hooks)
    # -------------------------------------------------------------
    def on_init(self):
        """策略初始化：设置指标参数、准备数据池"""
        pass

    def on_start(self):
        """策略启动：在回测开始或盘中开始前被调用"""
        pass

    @abstractmethod
    def on_bar(self, bar: Bar):
        """K 线切片事件 (日K或分钟K到达时触发)"""
        pass

    def on_snapshot(self, snapshot: Snapshot):
        """实时行情快照事件 (Tick/L1 变动时触发)"""
        pass

    def on_order_update(self, order: Order):
        """订单状态变更回调 (已报、部成、已成、已撤、废单)"""
        pass

    def on_trade(self, trade: Trade):
        """成交流水回调"""
        pass

    def on_stop(self):
        """策略停止：生成回测总结或盘后清理"""
        pass

    # -------------------------------------------------------------
    # 下单助手方法 (Order Helpers)
    # -------------------------------------------------------------
    def buy(
        self,
        symbol: str,
        quantity: float,
        price: Optional[float] = None,
        order_type: OrderType = OrderType.MARKET,
        reason: str = ""
    ) -> Order:
        """买入指令"""
        ts = self._get_current_timestamp(symbol)
        order = Order(
            order_id=f"ord_{uuid.uuid4().hex[:12]}",
            symbol=symbol,
            side=OrderSide.BUY,
            order_type=order_type,
            price=price,
            quantity=quantity,
            created_at=ts,
            updated_at=ts,
            reason=reason
        )
        self._pending_orders.append(order)
        return order

    def sell(
        self,
        symbol: str,
        quantity: float,
        price: Optional[float] = None,
        order_type: OrderType = OrderType.MARKET,
        reason: str = ""
    ) -> Order:
        """卖出指令"""
        ts = self._get_current_timestamp(symbol)
        order = Order(
            order_id=f"ord_{uuid.uuid4().hex[:12]}",
            symbol=symbol,
            side=OrderSide.SELL,
            order_type=order_type,
            price=price,
            quantity=quantity,
            created_at=ts,
            updated_at=ts,
            reason=reason
        )
        self._pending_orders.append(order)
        return order

    def order_target_percent(self, symbol: str, target_pct: float, reason: str = "") -> Optional[Order]:
        """目标仓位调仓助手 (如 target_pct = 0.2 代表将该标的调仓至占总资产的 20%)"""
        if not self.context:
            return None
        portfolio = self.context.portfolio
        total_equity = portfolio.total_equity
        target_value = total_equity * target_pct
        
        current_pos = portfolio.get_position(symbol)
        current_val = current_pos.market_value
        diff_val = target_value - current_val
        
        current_price = current_pos.current_price
        if current_price <= 0 and symbol in self.context.current_bars:
            current_price = self.context.current_bars[symbol].close
        
        if current_price <= 0:
            return None
            
        shares_diff = diff_val / current_price
        if abs(shares_diff) < 1.0:
            return None
            
        if shares_diff > 0:
            # 买入按整手取整或标准股数
            qty = int(shares_diff // 100) * 100 if "STK" in symbol or "ETF" in symbol else shares_diff
            if qty > 0:
                return self.buy(symbol, qty, price=current_price, reason=reason or f"Target {target_pct*100}%")
        else:
            # 卖出平仓
            qty = min(current_pos.available_quantity, abs(shares_diff))
            if qty > 0:
                return self.sell(symbol, qty, price=current_price, reason=reason or f"Target {target_pct*100}%")
        return None

    def close_position(self, symbol: str, reason: str = "Close all") -> Optional[Order]:
        """全仓平仓"""
        if not self.context:
            return None
        pos = self.context.portfolio.get_position(symbol)
        if pos.available_quantity > 0:
            return self.sell(symbol, pos.available_quantity, reason=reason)
        return None

    def get_position(self, symbol: str) -> Position:
        if self.context:
            return self.context.portfolio.get_position(symbol)
        return Position(symbol=symbol)

    def extract_pending_orders(self) -> List[Order]:
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders

    def _get_current_timestamp(self, symbol: str) -> int:
        if self.context and symbol in self.context.current_bars:
            return self.context.current_bars[symbol].timestamp
        return 0
