from quant_core.core.base_strategy import BaseStrategy
from quant_core.core.models import Bar

class DualMovingAverageStrategy(BaseStrategy):
    """
    经典双均线趋势策略 (Dual Moving Average Cross - QuantCore 2.0 极简流式架构)：
    - 短期均线 (如 MA5) 上穿 长期均线 (如 MA20) 形成金叉：买入开仓；
    - 短期均线 下穿 长期均线 形成死叉：卖出平仓止盈/止损。
    """
    def __init__(self, fast_period: int = 5, slow_period: int = 20):
        super().__init__(name="DualMA", params={"fast": fast_period, "slow": slow_period})
        self.fast = fast_period
        self.slow = slow_period

    def on_bar(self, bar: Bar):
        # 1. 均线金叉开仓 (Golden Cross)
        if bar.cross_over(self.fast, self.slow) and not self.position:
            self.order_target_percent(0.8, reason="Golden Cross Buy")

        # 2. 均线死叉平仓 (Death Cross)
        elif bar.cross_under(self.fast, self.slow) and self.position:
            self.close_position(reason="Death Cross Sell")
