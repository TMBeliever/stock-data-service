from quant_core.core.base_strategy import BaseStrategy
from quant_core.core.models import Bar

class ExtremeDipHeavyStrategy(BaseStrategy):
    """
    极端黄金坑一击打满策略 (Extreme Dip Heavy / One-Shot Dip All-In):
    
    【核心逻辑】
    1. 寻找黄金坑：在未建仓前全额保留现金储备观望，追踪标的阶段最高价与回撤幅度；
    2. 黄金坑打满：当从阶段峰值出现暴跌回调且跌幅 >= dip_threshold (默认 20%~25%)，判定为极端黄金坑，一次性 99% 全仓打满买入；
    3. 死拿不再动 (one_shot=True)：完成黄金坑打满后，后续永不减仓、永不调仓、永不卖出，永久死拿吃满后续所有长牛复利！
    4. 循环防守模式 (one_shot=False)：若关闭一击死拿模式，跌破长线均线时可缩减仓位防守，等待下一个黄金坑。
    """
    def __init__(
        self,
        dip_threshold: float = 0.20,
        one_shot: bool = True,
        heavy_pct: float = 0.99,
        ma_period: int = 120,
        defensive_pct: float = 0.20
    ):
        super().__init__(
            name="ExtremeDipHeavy",
            params={
                "dip_threshold": dip_threshold,
                "one_shot": one_shot,
                "heavy_pct": heavy_pct,
                "ma_period": ma_period,
                "defensive_pct": defensive_pct
            }
        )
        self.dip_threshold = dip_threshold
        self.one_shot = one_shot
        self.heavy_pct = heavy_pct
        self.ma_period = ma_period
        self.defensive_pct = defensive_pct
        self.peak_price: float = 0.0
        self.has_bought: bool = False
        self.buy_date: str = ""
        self.buy_price: float = 0.0

    def on_bar(self, bar: Bar):
        # 如果是“打满后绝不再动”模式且已经买入，则直接挂机死拿，不做任何调仓
        if self.one_shot and self.has_bought:
            return

        symbol = bar.symbol
        cur_price = bar.close
        self.peak_price = max(self.peak_price, cur_price)

        drawdown_from_peak = (self.peak_price - cur_price) / self.peak_price if self.peak_price > 0 else 0.0

        if self.one_shot:
            # 模式 A: 某一时刻黄金坑一击打满 -> 之后绝不再动
            if drawdown_from_peak >= self.dip_threshold and not self.has_bought:
                self.order_target_percent(symbol, self.heavy_pct, reason=f"Golden Pit Dip ({drawdown_from_peak:.1%}) All-In")
                self.has_bought = True
                self.buy_date = bar.date_str
                self.buy_price = cur_price
            return

        # 模式 B: 多周期循环跟踪模式 (one_shot=False)
        closes = self.context.get_closes(symbol, n=self.ma_period + 10)
        if len(closes) < self.ma_period:
            return
        ma = sum(closes[-self.ma_period:]) / self.ma_period

        if drawdown_from_peak >= self.dip_threshold:
            target_pct = self.heavy_pct
            reason = f"Extreme Dip ({drawdown_from_peak:.1%}) All-In"
        elif cur_price >= ma:
            target_pct = self.heavy_pct
            reason = "Bull Trend Hold"
        else:
            target_pct = self.defensive_pct
            reason = "Bearish Defense"

        portfolio = self.context.portfolio
        cur_pos = portfolio.get_position(symbol)
        total_equity = portfolio.total_equity
        if total_equity > 0:
            cur_pct = cur_pos.market_value / total_equity
            if abs(cur_pct - target_pct) >= 0.05:
                self.order_target_percent(symbol, target_pct, reason=reason)


