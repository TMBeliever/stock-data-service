from quant_core.core.base_strategy import BaseStrategy
from quant_core.core.models import Bar

class BuyAndHoldStrategy(BaseStrategy):
    """
    一次性买入并持有基准策略 (All-In Buy & Hold Strategy)：
    在回测首个交易日全仓买入目标标的 (如 99% 仓位以留存滑点规费)，
    之后全程被动持有不进行任何主动择时、止盈或调仓。
    作为评估主动量化策略/智能定投的经典基准对照组 (Benchmark)。
    """
    def __init__(self, target_pct: float = 0.99):
        super().__init__(name="BuyAndHold_AllIn", params={"target_pct": target_pct})
        self.target_pct = target_pct
        self.has_bought = False

    def on_bar(self, bar: Bar):
        if self.has_bought:
            return
        symbol = bar.symbol
        pos = self.get_position(symbol)
        if pos.quantity == 0:
            order = self.order_target_percent(symbol, self.target_pct, reason="Day 1 All-In Buy & Hold")
            if order:
                self.has_bought = True
