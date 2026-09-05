import uuid
from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any, Tuple, Union, Sequence
from quant_core.core.models import (
    Bar, Snapshot, Order, Trade, OrderSide, OrderType, OrderStatus, Position
)
from quant_core.core.context import StrategyContext
from quant_core.factors.technical import (
    sma as calc_sma,
    ema as calc_ema,
    rsi as calc_rsi,
    macd as calc_macd,
    bollinger_bands as calc_bb,
    atr as calc_atr,
)


class BaseStrategy(ABC):
    """
    量化策略抽象基类 (QuantCore 2.0 极简流式架构)：
    - 兼容事件驱动与函数式上下文；
    - 自动切片绑定 (Auto-Context Binding)；
    - 直观属性访问 (self.cash, self.equity, self.position, self.bars)；
    - 内置免 import 常用技术指标与金叉死叉算子 (self.sma, self.macd, self.cross_over 等)；
    - 高度容错的智能下单助手 (支持 self.buy(100), self.buy(bar), self.order_target_percent(0.8), self.close_position())。
    """

    def __init__(self, *args, **kwargs):
        name = "BaseStrategy"
        params: Dict[str, Any] = {}

        if len(args) == 1:
            if isinstance(args[0], str):
                name = args[0]
            elif isinstance(args[0], dict):
                params = dict(args[0])
        elif len(args) >= 2:
            if isinstance(args[0], str):
                name = args[0]
            if isinstance(args[1], dict):
                params = dict(args[1])

        if "name" in kwargs:
            name = kwargs.pop("name")
        if "params" in kwargs and isinstance(kwargs["params"], dict):
            params.update(kwargs.pop("params"))
        params.update(kwargs)

        self.name = name
        self.params = params
        self.context: Optional[StrategyContext] = None
        self._pending_orders: List[Order] = []
        self._current_bar: Optional[Bar] = None
        self._current_symbol: Optional[str] = None
        self._bars_storage: List[Bar] = []

    def set_context(self, context: StrategyContext):
        self.context = context

    def _set_current_bar(self, bar: Bar):
        """引擎在调度触发 on_bar 前自动绑定当前行情切片"""
        self._current_bar = bar
        self._current_symbol = bar.symbol

    # -------------------------------------------------------------
    # 极简核心属性快捷访问 (Intuitive Properties)
    # -------------------------------------------------------------
    @property
    def current_bar(self) -> Optional[Bar]:
        """当前处理的 K 线对象"""
        if self._current_bar:
            return self._current_bar
        if self.context and self.context.current_bars:
            return next(iter(self.context.current_bars.values()))
        return None

    @property
    def current_symbol(self) -> str:
        """当前标的代码"""
        if self._current_symbol:
            return self._current_symbol
        bar = self.current_bar
        return bar.symbol if bar else ""

    @property
    def cash(self) -> float:
        """可用现金 (CNY)"""
        if self.context:
            return self.context.portfolio.cash
        return 0.0

    @property
    def equity(self) -> float:
        """组合动态总权益 (现金 + 持仓总市值)"""
        if self.context:
            return self.context.portfolio.total_equity
        return 0.0

    @property
    def position(self) -> Position:
        """当前标的的持仓对象 (支持 `if self.position > 0:` 或 `if self.position:`)"""
        sym = self.current_symbol
        if sym and self.context:
            return self.context.portfolio.get_position(sym)
        return Position(symbol=sym or "")

    @property
    def positions(self) -> Dict[str, Position]:
        """所有标的的持仓字典"""
        if self.context:
            return self.context.portfolio.positions
        return {}

    @property
    def bars(self) -> List[Bar]:
        """当前标的历史已接收的所有 Bar 序列 (按时间升序)"""
        sym = self.current_symbol
        if sym and self.context:
            return self.context.get_history(sym, n=0)
        return self._bars_storage

    @bars.setter
    def bars(self, val: List[Bar]):
        self._bars_storage = val

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
        """订单状态变更回调"""
        pass

    def on_trade(self, trade: Trade):
        """成交流水回调"""
        pass

    def on_stop(self):
        """策略停止：生成回测总结或盘后清理"""
        pass

    # -------------------------------------------------------------
    # 历史序列快捷提取 (Data Series Helpers)
    # -------------------------------------------------------------
    def closes(self, n: Optional[int] = None, symbol: Optional[str] = None) -> List[float]:
        """获取最近 N 根收盘价列表 (默认当前标的，n=None 为全部)"""
        target = symbol or self.current_symbol
        if not target or not self.context:
            return [b.close for b in self._bars_storage[-n:] if n] if self._bars_storage else []
        return self.context.get_closes(target, n=n or 0)

    def opens(self, n: Optional[int] = None, symbol: Optional[str] = None) -> List[float]:
        """获取最近 N 根开盘价列表 (默认当前标的)"""
        target = symbol or self.current_symbol
        if not target or not self.context:
            return [b.open for b in self._bars_storage[-n:] if n] if self._bars_storage else []
        return self.context.get_opens(target, n=n or 0)

    def highs(self, n: Optional[int] = None, symbol: Optional[str] = None) -> List[float]:
        """获取最近 N 根最高价列表 (默认当前标的)"""
        target = symbol or self.current_symbol
        if not target or not self.context:
            return [b.high for b in self._bars_storage[-n:] if n] if self._bars_storage else []
        return self.context.get_highs(target, n=n or 0)

    def lows(self, n: Optional[int] = None, symbol: Optional[str] = None) -> List[float]:
        """获取最近 N 根最低价列表 (默认当前标的)"""
        target = symbol or self.current_symbol
        if not target or not self.context:
            return [b.low for b in self._bars_storage[-n:] if n] if self._bars_storage else []
        return self.context.get_lows(target, n=n or 0)

    def volumes(self, n: Optional[int] = None, symbol: Optional[str] = None) -> List[float]:
        """获取最近 N 根成交量列表 (默认当前标的)"""
        target = symbol or self.current_symbol
        if not target or not self.context:
            return [b.volume for b in self._bars_storage[-n:] if n] if self._bars_storage else []
        return self.context.get_volumes(target, n=n or 0)

    # -------------------------------------------------------------
    # 内置开箱即用技术指标 (Built-in Indicators)
    # -------------------------------------------------------------
    def sma(
        self,
        period: int = 20,
        series: Optional[Sequence[float]] = None,
        symbol: Optional[str] = None,
        offset: int = 0
    ) -> float:
        """简单移动平均 (SMA)，offset=0 为最新值，offset=1 为前一根 K 线值"""
        s = series if series is not None else self.closes(symbol=symbol)
        if offset > 0:
            s = s[:-offset] if len(s) > offset else []
        return calc_sma(s, period)

    def sma_series(
        self,
        period: int = 20,
        series: Optional[Sequence[float]] = None,
        symbol: Optional[str] = None
    ) -> List[float]:
        """计算完整 SMA 时间序列"""
        s = series if series is not None else self.closes(symbol=symbol)
        return [calc_sma(s[:i + 1], period) for i in range(len(s))]

    def ema(
        self,
        period: int = 20,
        series: Optional[Sequence[float]] = None,
        symbol: Optional[str] = None,
        offset: int = 0
    ) -> float:
        """指数移动平均 (EMA)"""
        s = series if series is not None else self.closes(symbol=symbol)
        if offset > 0:
            s = s[:-offset] if len(s) > offset else []
        return calc_ema(s, period)

    def rsi(
        self,
        period: int = 14,
        series: Optional[Sequence[float]] = None,
        symbol: Optional[str] = None,
        offset: int = 0
    ) -> float:
        """相对强弱指标 (RSI 0~100)"""
        s = series if series is not None else self.closes(symbol=symbol)
        if offset > 0:
            s = s[:-offset] if len(s) > offset else []
        return calc_rsi(s, period)

    def macd(
        self,
        fast: int = 12,
        slow: int = 26,
        signal: int = 9,
        series: Optional[Sequence[float]] = None,
        symbol: Optional[str] = None
    ) -> Tuple[float, float, float]:
        """MACD 指标：返回最新 (dif, dea, hist)"""
        s = series if series is not None else self.closes(symbol=symbol)
        return calc_macd(s, fast_period=fast, slow_period=slow, signal_period=signal)

    def bollinger_bands(
        self,
        period: int = 20,
        num_std: float = 2.0,
        series: Optional[Sequence[float]] = None,
        symbol: Optional[str] = None
    ) -> Tuple[float, float, float]:
        """布林带指标：返回最新 (upper, mid, lower)"""
        s = series if series is not None else self.closes(symbol=symbol)
        return calc_bb(s, period=period, num_std=num_std)

    def atr(
        self,
        period: int = 14,
        symbol: Optional[str] = None,
        offset: int = 0
    ) -> float:
        """真实波幅均值 (ATR)"""
        h = self.highs(symbol=symbol)
        l = self.lows(symbol=symbol)
        c = self.closes(symbol=symbol)
        if offset > 0:
            h = h[:-offset] if len(h) > offset else []
            l = l[:-offset] if len(l) > offset else []
            c = c[:-offset] if len(c) > offset else []
        return calc_atr(h, l, c, period)

    def highest(
        self,
        period: int = 20,
        series: Optional[Sequence[float]] = None,
        symbol: Optional[str] = None,
        include_current: bool = True
    ) -> float:
        """计算前 N 根 K 线的最高价 (默认从 highs 提取，include_current=False 排除当前正在进行的切片)"""
        s = series if series is not None else self.highs(symbol=symbol)
        if not s:
            return 0.0
        seq = s if include_current else s[:-1]
        if not seq:
            return 0.0
        sub = seq[-period:] if period > 0 else seq
        return float(max(sub)) if sub else 0.0

    def lowest(
        self,
        period: int = 20,
        series: Optional[Sequence[float]] = None,
        symbol: Optional[str] = None,
        include_current: bool = True
    ) -> float:
        """计算前 N 根 K 线的最低价 (默认从 lows 提取，include_current=False 排除当前正在进行的切片)"""
        s = series if series is not None else self.lows(symbol=symbol)
        if not s:
            return 0.0
        seq = s if include_current else s[:-1]
        if not seq:
            return 0.0
        sub = seq[-period:] if period > 0 else seq
        return float(min(sub)) if sub else 0.0

    def cross_over(self, a: Any, b: Any) -> bool:
        """
        金叉上穿判断：
        1. 若传入两个整数 (如 self.cross_over(5, 20))，自动以 SMA(5) 与 SMA(20) 判定金叉；
        2. 若传入两个价格序列 (如 self.cross_over(fast_series, slow_series))，取最新两点对比；
        3. 若传入两个二元元组 ((prev1, curr1), (prev2, curr2))。
        """
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

    def cross_under(self, a: Any, b: Any) -> bool:
        """
        死叉下穿判断：
        1. 若传入两个整数 (如 self.cross_under(5, 20))，自动以 SMA(5) 与 SMA(20) 判定死叉；
        2. 若传入两个价格序列 (如 self.cross_under(fast_series, slow_series))，取最新两点对比。
        """
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
    # 智能交易指令助手 (Smart Order Helpers)
    # -------------------------------------------------------------
    def buy(
        self,
        *args,
        symbol: Optional[str] = None,
        quantity: Optional[float] = None,
        price: Optional[float] = None,
        order_type: OrderType = OrderType.MARKET,
        reason: str = "",
        **kwargs
    ) -> Optional[Order]:
        """
        买入指令 (智能自适应参数)：
        支持:
        - self.buy(100) -> 标的默认当前 K 线, 买入 100 股
        - self.buy(bar) -> 买入当前 Bar 对应标的 (默认 100 股)
        - self.buy(bar, 100)
        - self.buy("510300", 100)
        - self.buy(100, price=3.5)
        """
        args_list = list(args)
        if args_list:
            first = args_list[0]
            if isinstance(first, Bar):
                symbol = first.symbol
                if price is None:
                    price = first.close
                args_list.pop(0)
            elif isinstance(first, str):
                symbol = first
                args_list.pop(0)

        if args_list and quantity is None and isinstance(args_list[0], (int, float)):
            quantity = float(args_list.pop(0))

        if args_list and price is None and isinstance(args_list[0], (int, float)):
            price = float(args_list.pop(0))

        symbol = symbol or self.current_symbol
        if not symbol:
            return None

        if quantity is None or quantity <= 0:
            quantity = 100.0

        cur_bar = self.current_bar
        if (price is None or price <= 0) and cur_bar and cur_bar.symbol == symbol:
            price = cur_bar.close

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
            reason=reason or kwargs.get("reason", "")
        )
        self._pending_orders.append(order)
        return order

    def sell(
        self,
        *args,
        symbol: Optional[str] = None,
        quantity: Optional[float] = None,
        price: Optional[float] = None,
        order_type: OrderType = OrderType.MARKET,
        reason: str = "",
        **kwargs
    ) -> Optional[Order]:
        """卖出指令 (智能自适应参数)"""
        args_list = list(args)
        if args_list:
            first = args_list[0]
            if isinstance(first, Bar):
                symbol = first.symbol
                if price is None:
                    price = first.close
                args_list.pop(0)
            elif isinstance(first, str):
                symbol = first
                args_list.pop(0)

        if args_list and quantity is None and isinstance(args_list[0], (int, float)):
            quantity = float(args_list.pop(0))

        if args_list and price is None and isinstance(args_list[0], (int, float)):
            price = float(args_list.pop(0))

        symbol = symbol or self.current_symbol
        if not symbol:
            return None

        if quantity is None or quantity <= 0:
            pos = self.get_position(symbol)
            quantity = pos.available_quantity if pos.available_quantity > 0 else 100.0

        cur_bar = self.current_bar
        if (price is None or price <= 0) and cur_bar and cur_bar.symbol == symbol:
            price = cur_bar.close

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
            reason=reason or kwargs.get("reason", "")
        )
        self._pending_orders.append(order)
        return order

    def order_target_percent(
        self,
        *args,
        symbol: Optional[str] = None,
        target_pct: Optional[float] = None,
        reason: str = "",
        **kwargs
    ) -> Optional[Order]:
        """
        目标仓位调仓助手 (支持自适应入参)：
        - self.order_target_percent(0.8) -> 当前标的调仓至总权益 80%
        - self.order_target_percent("510300", 0.8)
        - self.order_target_percent(bar, 0.8)
        """
        if not self.context:
            return None

        args_list = list(args)
        if args_list:
            first = args_list[0]
            if isinstance(first, (int, float)):
                target_pct = float(args_list.pop(0))
            elif isinstance(first, Bar):
                symbol = args_list.pop(0).symbol
            elif isinstance(first, str):
                symbol = args_list.pop(0)

        if args_list and target_pct is None and isinstance(args_list[0], (int, float)):
            target_pct = float(args_list.pop(0))

        if args_list and not reason and isinstance(args_list[0], str):
            reason = args_list.pop(0)

        symbol = symbol or self.current_symbol
        if not symbol or target_pct is None:
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
        if current_price <= 0 and self.current_bar:
            current_price = self.current_bar.close

        if current_price <= 0:
            return None

        shares_diff = diff_val / current_price
        if abs(shares_diff) < 1.0:
            return None

        if shares_diff > 0:
            qty = int(shares_diff // 100) * 100 if ("STK" in symbol or "ETF" in symbol or len(symbol) == 6 or "." in symbol) else shares_diff
            if qty > 0:
                return self.buy(symbol=symbol, quantity=qty, price=current_price, reason=reason or f"Target {target_pct * 100}%")
        else:
            qty = min(current_pos.available_quantity, abs(shares_diff))
            if qty > 0:
                return self.sell(symbol=symbol, quantity=qty, price=current_price, reason=reason or f"Target {target_pct * 100}%")

        return None

    def close_position(
        self,
        *args,
        symbol: Optional[str] = None,
        reason: str = "Close all",
        **kwargs
    ) -> Optional[Order]:
        """
        全仓平仓指令助手：
        - self.close_position() -> 平掉当前标的所有可用仓位
        - self.close_position(bar)
        - self.close_position("510300")
        """
        for a in args:
            if isinstance(a, Bar):
                symbol = a.symbol
            elif isinstance(a, str):
                if symbol is None:
                    symbol = a
                else:
                    reason = a

        symbol = symbol or self.current_symbol
        if not symbol or not self.context:
            return None

        pos = self.context.portfolio.get_position(symbol)
        if pos.available_quantity > 0:
            return self.sell(symbol=symbol, quantity=pos.available_quantity, reason=reason)
        return None

    def get_position(self, symbol: Optional[str] = None) -> Position:
        """获取指定标的或当前标的的持仓对象"""
        sym = symbol or self.current_symbol
        if self.context and sym:
            return self.context.portfolio.get_position(sym)
        return Position(symbol=sym or "")

    def extract_pending_orders(self) -> List[Order]:
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders

    def _get_current_timestamp(self, symbol: str) -> int:
        if self.context and symbol in self.context.current_bars:
            return self.context.current_bars[symbol].timestamp
        if self.current_bar:
            return self.current_bar.timestamp
        return 0
