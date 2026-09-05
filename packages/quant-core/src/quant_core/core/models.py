import datetime
from enum import Enum
from typing import Optional, Dict, List, Any, Tuple, Union, Sequence
from pydantic import BaseModel, Field, PrivateAttr

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
    """
    K 线行情切片模型 (QuantCore 2.0 智能切片)：
    - 基础时序行情：symbol, timestamp, open, high, low, close, volume, amount, period
    - 基础衍生属性：change, change_pct, amplitude, is_up, is_down
    - 财务/估值字段：pe, pb, ps, turnover_rate
    - 上下文智能代理 (Auto-Context Proxy)：
      - history(n): 最近 n 根 K 线列表
      - closes(n), opens(n), highs(n), lows(n), volumes(n)
      - sma(period), ema(period), rsi(period), macd(), atr()
      - highest(period), lowest(period)
      - cross_over(fast, slow), cross_under(fast, slow)
      - percentile(window): 价格历史分位数 (0.0~1.0)
      - is_undervalued: 是否处于低估区间 (分位数 <= 20% 或 PE < 15)
      - is_overvalued: 是否处于高估泡沫区间 (分位数 >= 80% 或 PE > 50)
    """
    symbol: str
    timestamp: int  # UTC Epoch 毫秒时间戳
    open: float
    high: float
    low: float
    close: float
    volume: float
    amount: Optional[float] = None
    period: str = "1d"
    prev_close: Optional[float] = None  # 昨收盘价

    # 财务与估值属性 (股票/ETF 可选)
    pe: Optional[float] = None          # 市盈率 (PE_TTM)
    pb: Optional[float] = None          # 市净率 (PB)
    ps: Optional[float] = None          # 市销率 (PS)
    turnover_rate: Optional[float] = None  # 换手率 (%)

    # 私有上下文绑定 (用于历史序列与指标计算，不参与序列化)
    _context: Any = PrivateAttr(default=None)

    @property
    def dt(self) -> datetime.datetime:
        """转换毫秒为 UTC 日期时间对象"""
        return datetime.datetime.fromtimestamp(self.timestamp / 1000.0, datetime.timezone.utc)

    @property
    def date_str(self) -> str:
        """YYYY-MM-DD 日期字符串"""
        return self.dt.strftime("%Y-%m-%d")

    @property
    def change(self) -> float:
        """价格涨跌额 (优先根据昨收对比，否则对比今开)"""
        base = self.prev_close if self.prev_close and self.prev_close > 0 else self.open
        return round(self.close - base, 4)

    @property
    def change_pct(self) -> float:
        """价格涨跌幅比例 (如 0.03 代表 +3%)"""
        base = self.prev_close if self.prev_close and self.prev_close > 0 else self.open
        return round((self.close - base) / base, 6) if base > 0 else 0.0

    @property
    def amplitude(self) -> float:
        """日内振幅 ((最高 - 最低) / 昨收或开盘)"""
        base = self.prev_close if self.prev_close and self.prev_close > 0 else self.open
        return round((self.high - self.low) / base, 6) if base > 0 else 0.0

    @property
    def is_up(self) -> bool:
        """是否收阳线 (收盘 >= 开盘)"""
        return self.close >= self.open

    @property
    def is_down(self) -> bool:
        """是否收阴线 (收盘 < 开盘)"""
        return self.close < self.open

    def bind_context(self, context: Any) -> "Bar":
        """挂载上下文引用 (使 Bar 能够感知自身标的历史数据与指标)"""
        self._context = context
        return self

    # -------------------------------------------------------------
    # 标的历史切片快捷方法
    # -------------------------------------------------------------
    def history(self, n: int = 50) -> List["Bar"]:
        """获取当前标的历史 N 根 Bar"""
        if self._context and hasattr(self._context, "get_history"):
            return self._context.get_history(self.symbol, n=n)
        return [self]

    def closes(self, n: int = 50) -> List[float]:
        """获取当前标的历史 N 根收盘价"""
        if self._context and hasattr(self._context, "get_closes"):
            return self._context.get_closes(self.symbol, n=n)
        return [self.close]

    def highs(self, n: int = 50) -> List[float]:
        if self._context and hasattr(self._context, "get_highs"):
            return self._context.get_highs(self.symbol, n=n)
        return [self.high]

    def lows(self, n: int = 50) -> List[float]:
        if self._context and hasattr(self._context, "get_lows"):
            return self._context.get_lows(self.symbol, n=n)
        return [self.low]

    def opens(self, n: int = 50) -> List[float]:
        if self._context and hasattr(self._context, "get_opens"):
            return self._context.get_opens(self.symbol, n=n)
        return [self.open]

    def volumes(self, n: int = 50) -> List[float]:
        if self._context and hasattr(self._context, "get_volumes"):
            return self._context.get_volumes(self.symbol, n=n)
        return [self.volume]

    # -------------------------------------------------------------
    # 内置开箱即用技术指标
    # -------------------------------------------------------------
    def sma(self, period: int = 20, offset: int = 0) -> float:
        """计算当前标的的 SMA 均线 (offset=0 为最新值，offset=1 为前一日)"""
        from quant_core.factors.technical import sma as calc_sma
        c = self.closes(n=period + offset + 5)
        if offset > 0:
            c = c[:-offset] if len(c) > offset else []
        return calc_sma(c, period)

    def ema(self, period: int = 20, offset: int = 0) -> float:
        """计算当前标的的 EMA 均线"""
        from quant_core.factors.technical import ema as calc_ema
        c = self.closes(n=period + offset + 5)
        if offset > 0:
            c = c[:-offset] if len(c) > offset else []
        return calc_ema(c, period)

    def rsi(self, period: int = 14, offset: int = 0) -> float:
        """计算当前标的的 RSI (0~100)"""
        from quant_core.factors.technical import rsi as calc_rsi
        c = self.closes(n=period + offset + 10)
        if offset > 0:
            c = c[:-offset] if len(c) > offset else []
        return calc_rsi(c, period)

    def macd(self, fast: int = 12, slow: int = 26, signal: int = 9) -> Tuple[float, float, float]:
        """计算当前标的的 MACD: 返回 (dif, dea, hist)"""
        from quant_core.factors.technical import macd as calc_macd
        c = self.closes(n=slow + signal + 10)
        return calc_macd(c, fast_period=fast, slow_period=slow, signal_period=signal)

    def atr(self, period: int = 14, offset: int = 0) -> float:
        """计算当前标的的 ATR 真实波幅"""
        from quant_core.factors.technical import atr as calc_atr
        h = self.highs(n=period + offset + 5)
        l = self.lows(n=period + offset + 5)
        c = self.closes(n=period + offset + 5)
        if offset > 0:
            h = h[:-offset] if len(h) > offset else []
            l = l[:-offset] if len(l) > offset else []
            c = c[:-offset] if len(c) > offset else []
        return calc_atr(h, l, c, period)

    def highest(self, period: int = 20, include_current: bool = True) -> float:
        """获取过去 N 根 K 线的最高价 (唐奇安通道上轨)"""
        h = self.highs(n=period + 1)
        seq = h if include_current else h[:-1]
        sub = seq[-period:] if period > 0 else seq
        return float(max(sub)) if sub else self.high

    def lowest(self, period: int = 20, include_current: bool = True) -> float:
        """获取过去 N 根 K 线的最低价 (唐奇安通道下轨)"""
        l = self.lows(n=period + 1)
        seq = l if include_current else l[:-1]
        sub = seq[-period:] if period > 0 else seq
        return float(min(sub)) if sub else self.low

    def cross_over(self, a: Union[int, Sequence[float]], b: Union[int, Sequence[float]]) -> bool:
        """金叉上穿判断 (支持 bar.cross_over(5, 20))"""
        if isinstance(a, int) and isinstance(b, int):
            prev_a = self.sma(a, offset=1)
            curr_a = self.sma(a, offset=0)
            prev_b = self.sma(b, offset=1)
            curr_b = self.sma(b, offset=0)
            if prev_a == 0 or prev_b == 0 or curr_a == 0 or curr_b == 0:
                return False
            return prev_a <= prev_b and curr_a > curr_b
        if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
            if len(a) < 2 or len(b) < 2:
                return False
            return a[-2] <= b[-2] and a[-1] > b[-1]
        return False

    def cross_under(self, a: Union[int, Sequence[float]], b: Union[int, Sequence[float]]) -> bool:
        """死叉下穿判断 (支持 bar.cross_under(5, 20))"""
        if isinstance(a, int) and isinstance(b, int):
            prev_a = self.sma(a, offset=1)
            curr_a = self.sma(a, offset=0)
            prev_b = self.sma(b, offset=1)
            curr_b = self.sma(b, offset=0)
            if prev_a == 0 or prev_b == 0 or curr_a == 0 or curr_b == 0:
                return False
            return prev_a >= prev_b and curr_a < curr_b
        if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
            if len(a) < 2 or len(b) < 2:
                return False
            return a[-2] >= b[-2] and a[-1] < b[-1]
        return False

    # -------------------------------------------------------------
    # 估值分位数与高低估智能判断
    # -------------------------------------------------------------
    def percentile(self, window: int = 250) -> float:
        """计算收盘价在过去 window 个交易日的历史价格分位数 (0.0 ~ 1.0)"""
        c = self.closes(n=window)
        if len(c) < 5:
            return 0.5
        less_cnt = sum(1 for p in c if p < self.close)
        return round(less_cnt / len(c), 4)

    @property
    def is_undervalued(self) -> bool:
        """是否处于深度低估区间 (过去 250 日价格分位数 <= 20% 或 PE < 15)"""
        if self.pe is not None and 0 < self.pe < 15:
            return True
        return self.percentile(250) <= 0.20

    @property
    def is_overvalued(self) -> bool:
        """是否处于高估泡沫区间 (过去 250 日价格分位数 >= 80% 或 PE > 50)"""
        if self.pe is not None and self.pe > 50:
            return True
        return self.percentile(250) >= 0.80

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

    def __bool__(self) -> bool:
        """持仓量大于 0 时为真，支持 `if self.position:` 或 `if not self.position:` 逻辑判断"""
        return self.quantity > 0

    def __gt__(self, other: Any) -> bool:
        if isinstance(other, (int, float)):
            return self.quantity > other
        if isinstance(other, Position):
            return self.quantity > other.quantity
        return NotImplemented

    def __ge__(self, other: Any) -> bool:
        if isinstance(other, (int, float)):
            return self.quantity >= other
        if isinstance(other, Position):
            return self.quantity >= other.quantity
        return NotImplemented

    def __lt__(self, other: Any) -> bool:
        if isinstance(other, (int, float)):
            return self.quantity < other
        if isinstance(other, Position):
            return self.quantity < other.quantity
        return NotImplemented

    def __le__(self, other: Any) -> bool:
        if isinstance(other, (int, float)):
            return self.quantity <= other
        if isinstance(other, Position):
            return self.quantity <= other.quantity
        return NotImplemented

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, (int, float)):
            return self.quantity == other
        if isinstance(other, Position):
            return self.quantity == other.quantity and self.symbol == other.symbol
        return super().__eq__(other)

    def __float__(self) -> float:
        return float(self.quantity)

    def __int__(self) -> int:
        return int(self.quantity)

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
