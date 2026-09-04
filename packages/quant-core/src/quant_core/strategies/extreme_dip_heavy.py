from quant_core.core.base_strategy import BaseStrategy
from quant_core.core.models import Bar

class ExtremeDipHeavyStrategy(BaseStrategy):
    """
    长牛趋势跟踪 + 极端低谷黄金坑一击打满策略 (Extreme Dip Heavy Accumulation):
    
    【核心逻辑】
    1. 暴跌黄金坑一击打满 (Crash Dip Heavy Buy):
       当标的从近期最高点回撤跌幅 >= dip_threshold (默认 20%~25%，如 2015 熔断、2020 疫情、2022 加息):
       策略判定出现极端黄金坑，一次性 98% 满仓打满，将全部储备资金转化为廉价底部筹码！
    2. 多头主升浪顺势持有 (Trend Full Holding):
       当价格处于长期均线 (默认 MA120/MA200) 上方，判定为多头行情，维持 98% 满仓持有，杜绝频繁止盈卖飞！
    3. 破位震荡防守控仓 (Bearish Defensive):
       当跌破长期均线但尚未跌出极端黄金坑时，自动缩减仓位至 defensive_pct (默认 20%~30%)，
       主动锁定部分利润，保存充足的真金白银子弹，耐心等待下一次极端暴跌机会。
    """
    def __init__(
        self,
        ma_period: int = 120,
        dip_threshold: float = 0.20,
        defensive_pct: float = 0.20,
        heavy_pct: float = 0.98
    ):
        super().__init__(
            name="ExtremeDipHeavy",
            params={
                "ma_period": ma_period,
                "dip_threshold": dip_threshold,
                "defensive_pct": defensive_pct,
                "heavy_pct": heavy_pct
            }
        )
        self.ma_period = ma_period
        self.dip_threshold = dip_threshold
        self.defensive_pct = defensive_pct
        self.heavy_pct = heavy_pct
        self.peak_price: float = 0.0

    def on_bar(self, bar: Bar):
        symbol = bar.symbol
        closes = self.context.get_closes(symbol, n=self.ma_period + 10)
        if len(closes) < self.ma_period:
            return

        ma = sum(closes[-self.ma_period:]) / self.ma_period
        cur_price = bar.close
        self.peak_price = max(self.peak_price, cur_price)

        # 计算从阶段峰值的回撤幅度
        drawdown_from_peak = (self.peak_price - cur_price) / self.peak_price if self.peak_price > 0 else 0.0

        # 规则 1: 极端暴跌黄金坑 -> 一击满仓打满!
        if drawdown_from_peak >= self.dip_threshold:
            target_pct = self.heavy_pct
            reason = f"Extreme Dip ({drawdown_from_peak:.1%}) All-In"
        # 规则 2: 处于长期多头趋势 -> 满仓持有吃满主升浪
        elif cur_price >= ma:
            target_pct = self.heavy_pct
            reason = "Bull Trend Hold"
        # 规则 3: 破位下行且未跌透 -> 控仓防守保留子弹
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

