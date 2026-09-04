from quant_system.core.base_strategy import BaseStrategy
from quant_system.core.models import Bar

class DividendETFRebalanceStrategy(BaseStrategy):
    """
    红利/价值 ETF 分位数动态定投与调仓策略：
    - 计算过去 120 天的价格分位数；
    - 极度低估 (<20%)：加大仓位至 90%；
    - 合理估值 (20%~80%)：维持标准仓位 50%；
    - 显著高估 (>80%)：主动止盈控仓至 10%。
    """
    def __init__(self, window: int = 120):
        super().__init__(name="DividendRebalance", params={"window": window})
        self.window = window

    def on_bar(self, bar: Bar):
        symbol = bar.symbol
        closes = self.context.get_closes(symbol, n=self.window)
        if len(closes) < 30:
            return

        min_p = min(closes)
        max_p = max(closes)
        if max_p == min_p:
            return

        # 计算百分比分位数
        pct = (bar.close - min_p) / (max_p - min_p)

        if pct < 0.20:
            self.order_target_percent(symbol, 0.90, reason=f"Deep Undervalue (pct={pct:.2f})")
        elif pct > 0.80:
            self.order_target_percent(symbol, 0.10, reason=f"Overvalued Trim (pct={pct:.2f})")
        else:
            self.order_target_percent(symbol, 0.50, reason=f"Normal Value (pct={pct:.2f})")
