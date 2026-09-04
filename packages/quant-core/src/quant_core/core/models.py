import datetime
from enum import Enum
from typing import Optional, Dict, List, Any
from pydantic import BaseModel, Field

class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"

class OrderType(str, Enum):
    MARKET = "MARKET"  # 市价单
    LIMIT = "LIMIT"    # 限价单
    STOP = "STOP"      # 止损单

class OrderStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    FILLED = "FILLED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"

class Bar(BaseModel):
    """K 线行情切片"""
    symbol: str
    timestamp: int  # UTC Epoch 毫秒时间戳
    open: float
    high: float
    low: float
    close: float
    volume: float
    amount: Optional[float] = None
    period: str = "1d"

    @property
    def dt(self) -> datetime.datetime:
        """转换毫秒为 UTC 日期时间对象"""
        return datetime.datetime.fromtimestamp(self.timestamp / 1000.0, datetime.timezone.utc)

    @property
    def date_str(self) -> str:
        """YYYY-MM-DD 日期字符串"""
        return self.dt.strftime("%Y-%m-%d")

class Snapshot(BaseModel):
    """L1 / 盘中行情快照"""
    symbol: str
    timestamp: int  # UTC Epoch 毫秒
    price: float
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    prev_close: float = 0.0
    volume: float = 0.0
    turnover: float = 0.0
    bid_price1: Optional[float] = None
    bid_volume1: Optional[float] = None
    ask_price1: Optional[float] = None
    ask_volume1: Optional[float] = None

class Order(BaseModel):
    """交易订单"""
    order_id: str
    symbol: str
    side: OrderSide
    order_type: OrderType = OrderType.MARKET
    price: Optional[float] = None
    quantity: float
    filled_quantity: float = 0.0
    filled_avg_price: float = 0.0
    status: OrderStatus = OrderStatus.SUBMITTED
    created_at: int  # UTC 毫秒
    updated_at: int
    reason: str = ""

    @property
    def is_active(self) -> bool:
        return self.status in (OrderStatus.SUBMITTED, OrderStatus.PARTIALLY_FILLED)

class Trade(BaseModel):
    """成交流水"""
    trade_id: str
    order_id: str
    symbol: str
    side: OrderSide
    price: float
    quantity: float
    commission: float = 0.0
    tax: float = 0.0
    slippage: float = 0.0
    timestamp: int  # UTC 毫秒

class Position(BaseModel):
    """个股持仓模型 (支持 A 股 T+1 约束)"""
    symbol: str
    quantity: float = 0.0            # 总持仓量
    available_quantity: float = 0.0  # 可卖出数量 (T+1 限制)
    avg_cost: float = 0.0            # 持仓均价成本
    current_price: float = 0.0       # 最新市价
    realized_pnl: float = 0.0        # 累计已实现盈亏

    @property
    def market_value(self) -> float:
        return self.quantity * self.current_price

    @property
    def unrealized_pnl(self) -> float:
        if self.quantity <= 0:
            return 0.0
        return (self.current_price - self.avg_cost) * self.quantity

    @property
    def return_ratio(self) -> float:
        if self.avg_cost <= 0:
            return 0.0
        return (self.current_price - self.avg_cost) / self.avg_cost

    def update_price(self, price: float):
        if price > 0:
            self.current_price = price

    def apply_trade(self, trade: Trade, t_plus_one: bool = True):
        """更新成交对持仓的影响"""
        self.update_price(trade.price)
        if trade.side == OrderSide.BUY:
            total_cost = self.avg_cost * self.quantity + trade.price * trade.quantity + trade.commission
            self.quantity += trade.quantity
            self.avg_cost = total_cost / self.quantity if self.quantity > 0 else 0.0
            # A 股 T+1: 当天买入不可卖，非 T+1 则直接立即可用
            if not t_plus_one:
                self.available_quantity += trade.quantity
        elif trade.side == OrderSide.SELL:
            sell_qty = trade.quantity
            # 计算平仓收益
            pnl = (trade.price - self.avg_cost) * sell_qty - trade.commission - trade.tax
            self.realized_pnl += pnl
            self.quantity = max(0.0, self.quantity - sell_qty)
            self.available_quantity = max(0.0, self.available_quantity - sell_qty)
            if self.quantity == 0:
                self.avg_cost = 0.0

    def settle_day_end(self):
        """交易日结束结算：解除 T+1 锁定，当日买入全部转为次日可卖"""
        self.available_quantity = self.quantity

class Portfolio(BaseModel):
    """投资组合账户模型"""
    initial_cash: float
    cash: float
    frozen_cash: float = 0.0
    positions: Dict[str, Position] = Field(default_factory=dict)
    trades: List[Trade] = Field(default_factory=list)
    daily_history: List[Dict[str, Any]] = Field(default_factory=list)

    @property
    def total_market_value(self) -> float:
        return sum(p.market_value for p in self.positions.values())

    @property
    def total_equity(self) -> float:
        """总权益 = 可用现金 + 冻结现金 + 持仓总市值"""
        return self.cash + self.frozen_cash + self.total_market_value

    @property
    def total_pnl(self) -> float:
        return self.total_equity - self.initial_cash

    @property
    def total_return(self) -> float:
        if self.initial_cash <= 0:
            return 0.0
        return self.total_pnl / self.initial_cash

    def get_position(self, symbol: str) -> Position:
        if symbol not in self.positions:
            self.positions[symbol] = Position(symbol=symbol)
        return self.positions[symbol]
