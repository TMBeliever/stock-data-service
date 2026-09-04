import datetime
from typing import Optional
from quant_core.core.base_strategy import BaseStrategy
from quant_core.core.models import Bar
from quant_core.factors.value import percentile_rank

class SmartDividendDCAStrategy(BaseStrategy):
    """
    红利低波 ETF 估值分位数智能定投与动态止盈策略 (Smart Dividend Low Volatility DCA):
    
    【核心机制】
    1. 每周第一个交易日执行一次定投评估；
    2. 计算过去 250 天 (约 1 年) 的滚动价格分位数 (0.0 ~ 1.0)；
    3. 动态资金调节：
       - 深度低估 (分位数 < 20%)：加大定投金额至 2.0 倍 (抄底低吸)；
       - 温和低估 (20% ~ 40%)：加大定投金额至 1.5 倍；
       - 正常估值 (40% ~ 70%)：基准定投金额 1.0 倍；
       - 偏高估值 (70% ~ 85%)：减少定投金额至 0.5 倍 (防守控仓)；
       - 极度泡沫 (分位数 > 85%)：暂停定投，并触发阶梯止盈 (卖出 20% 可用持仓锁利)；
    4. 买入强制按 A 股 100 股整手向下取整，卖出支持整手止盈。
    """
    def __init__(
        self,
        base_amount: float = 1000.0,
        window: int = 250,
        enable_take_profit: bool = True
    ):
        super().__init__(
            name="SmartDividendDCA",
            params={
                "base_amount": base_amount,
                "window": window,
                "enable_take_profit": enable_take_profit
            }
        )
        self.base_amount = base_amount
        self.window = window
        self.enable_take_profit = enable_take_profit
        
        self.last_invest_week: Optional[int] = None
        self.total_invested_cash: float = 0.0
        self.dca_count: int = 0

    def on_bar(self, bar: Bar):
        symbol = bar.symbol
        dt = bar.dt
        week_num = dt.isocalendar()[1]
        
        # 确保每周仅在首个交易日触发定投
        if week_num == self.last_invest_week:
            return
            
        closes = self.context.get_closes(symbol, n=self.window)
        if len(closes) < 30:
            return

        # 1. 计算价格在过去 window 天内的分位数 (0.0 ~ 1.0)
        pct = percentile_rank(bar.close, closes)
        self.last_invest_week = week_num
        self.dca_count += 1
        pos = self.get_position(symbol)

        # 2. 泡沫区间主动止盈 (分位数 > 85% 且持有可用仓位)
        if self.enable_take_profit and pct > 0.85 and pos.available_quantity >= 100:
            trim_qty = int((pos.available_quantity * 0.20) // 100) * 100
            if trim_qty > 0:
                self.sell(symbol, trim_qty, reason=f"Bubble Take Profit (pct={pct:.2f})")
                return

        # 3. 估值分位数梯度倍数
        if pct < 0.20:
            multiplier = 2.0   # 极度低估: 2倍
        elif pct < 0.40:
            multiplier = 1.5   # 温和低估: 1.5倍
        elif pct <= 0.70:
            multiplier = 1.0   # 正常估值: 1倍
        elif pct <= 0.85:
            multiplier = 0.5   # 偏高估值: 0.5倍
        else:
            multiplier = 0.0   # 极高估值: 暂停定投

        target_budget = self.base_amount * multiplier
        if target_budget <= 0:
            return

        # 4. 换算整手买入股数 (必须为 100 股整数倍)
        shares_diff = target_budget / bar.close
        buy_qty = int(shares_diff // 100) * 100

        if buy_qty > 0:
            # 校验账户现金是否充足
            if self.context.portfolio.cash >= buy_qty * bar.close * 1.001:
                self.buy(symbol, buy_qty, reason=f"DCA {multiplier}x (pct={pct:.2f})")
                self.total_invested_cash += buy_qty * bar.close
