from quant_system.core.base_strategy import BaseStrategy
from quant_system.core.models import Bar

class DualMovingAverageStrategy(BaseStrategy):
    """
    经典双均线趋势策略 (Dual Moving Average Cross)：
    - 短期均线 (如 MA5) 上穿 长期均线 (如 MA20) 形成金叉：买入开仓；
    - 短期均线 下穿 长期均线 形成死叉：卖出平仓止盈/止损。
    """
    def __init__(self, fast_period: int = 5, slow_period: int = 20):
        super().__init__(name="DualMA", params={"fast": fast_period, "slow": slow_period})
        self.fast = fast_period
        self.slow = slow_period

    def on_bar(self, bar: Bar):
        symbol = bar.symbol
        closes = self.context.get_closes(symbol, n=self.slow + 2)
        if len(closes) < self.slow + 1:
            return

        ma_fast_prev = sum(closes[-self.fast-1:-1]) / self.fast
        ma_fast_curr = sum(closes[-self.fast:]) / self.fast

        ma_slow_prev = sum(closes[-self.slow-1:-1]) / self.slow
        ma_slow_curr = sum(closes[-self.slow:]) / self.slow

        pos = self.get_position(symbol)

        # 金叉买入 (Golden Cross)
        if ma_fast_prev <= ma_slow_prev and ma_fast_curr > ma_slow_curr:
            if pos.quantity == 0:
                self.order_target_percent(symbol, 0.8, reason="Golden Cross Buy")

        # 死叉卖出 (Death Cross)
        elif ma_fast_prev >= ma_slow_prev and ma_fast_curr < ma_slow_curr:
            if pos.available_quantity > 0:
                self.close_position(symbol, reason="Death Cross Sell")
