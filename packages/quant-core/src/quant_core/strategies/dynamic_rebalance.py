from quant_core.core.base_strategy import BaseStrategy
from quant_core.core.models import Bar

class DynamicRebalanceStrategy(BaseStrategy):
    """
    自适应动态再平衡策略 (Dynamic Constant-Proportion Rebalancing):
    
    【核心机制】
    1. 保持目标权益仓位 target_pct (默认 85%) + 备用金 (15%)；
    2. 当行情持续上涨使持仓占比突破上限 (例如 > 90%) 时：
       自动卖出浮盈部分，将牛市利润收回充实安全备用金池 (实现自动止盈落袋)；
    3. 当行情剧烈下跌使持仓占比跌破下限 (例如 < 80%) 时：
       自动动用备用金池低位抄底加仓，将仓位补回 85% 目标水平 (实现自动逢低吸筹)；
    4. 投资哲学 (香农恶魔效应 Shannon's Demon)：
       利用指数的内生波动率，在“牛市抽水、熊市注水”的自动摆动中持续赚取再平衡溢价，
       在享受长期指数长牛复利的同时，大幅降低满仓死拿的最大回撤与心理压力。
    """
    def __init__(
        self,
        target_pct: float = 0.85,
        rebalance_band: float = 0.05,
        check_interval: int = 5
    ):
        super().__init__(
            name="DynamicRebalance",
            params={
                "target_pct": target_pct,
                "rebalance_band": rebalance_band,
                "check_interval": check_interval
            }
        )
        self.target_pct = target_pct
        self.rebalance_band = rebalance_band
        self.check_interval = check_interval
        self.counter = 0

    def on_bar(self, bar: Bar):
        self.counter += 1
        # 每隔 check_interval 个交易日 (如每周) 执行一次再平衡评估
        if self.counter % self.check_interval != 0:
            return

        portfolio = self.context.portfolio
        cur_pos = portfolio.get_position(bar.symbol)
        total_equity = portfolio.total_equity
        if total_equity <= 0:
            return

        cur_pct = cur_pos.market_value / total_equity

        # 当实际仓位偏离目标仓位超过阈值带宽时触发调仓
        if abs(cur_pct - self.target_pct) >= self.rebalance_band:
            action = "Take Profit Rebalance" if cur_pct > self.target_pct else "Dip Buying Rebalance"
            self.order_target_percent(
                bar.symbol,
                self.target_pct,
                reason=f"{action} ({cur_pct:.1%} -> {self.target_pct:.1%})"
            )
