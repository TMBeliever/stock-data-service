from typing import List, Dict, Optional, Any
from quant_core.core.models import Bar, Order, Trade, Portfolio
from quant_core.core.context import StrategyContext
from quant_core.core.base_strategy import BaseStrategy
from quant_core.backtest.broker import SimulatedBroker
from quant_core.backtest.metrics import PerformanceAnalytics, BacktestResult

class BacktestEngine:
    """
    事件驱动回测引擎 (Backtest Engine)：
    1. 收集全宇宙标的历史 K 线；
    2. 按绝对时间序列毫秒严格步进推进；
    3. 杜绝未来函数，步进前下发行情切片，步进中撮合策略订单；
    4. 执行 T+1 盘后结算与每日资产净值快照记录；
    5. 输出专业量化业绩评估报表。
    """
    def __init__(
        self,
        strategy: BaseStrategy,
        broker: Optional[SimulatedBroker] = None,
        initial_cash: float = 100_000.0
    ):
        self.strategy = strategy
        self.broker = broker or SimulatedBroker()
        self.initial_cash = initial_cash
        self.portfolio = Portfolio(initial_cash=initial_cash, cash=initial_cash)
        self.context = StrategyContext(portfolio=self.portfolio)
        self.strategy.set_context(self.context)

    def run(self, symbol_bars: Dict[str, List[Bar]]) -> BacktestResult:
        """运行回测主循环"""
        self.strategy.on_init()
        self.strategy.on_start()

        # 1. 建立全局时间序列队列
        all_timestamps = set()
        bars_by_ts: Dict[int, Dict[str, Bar]] = {}

        for sym, bars in symbol_bars.items():
            for b in bars:
                all_timestamps.add(b.timestamp)
                if b.timestamp not in bars_by_ts:
                    bars_by_ts[b.timestamp] = {}
                bars_by_ts[b.timestamp][sym] = b

        sorted_timestamps = sorted(list(all_timestamps))
        daily_records: List[Dict[str, Any]] = []

        last_date_str = ""

        # 2. 严格按时间步进推进
        num_steps = len(sorted_timestamps)
        for idx, ts in enumerate(sorted_timestamps):
            current_bar_map = bars_by_ts[ts]

            # 2.1 更新当前行情并送入策略上下文
            for sym, bar in current_bar_map.items():
                self.context.record_bar(bar)
                pos = self.portfolio.get_position(sym)
                pos.update_price(bar.close)

            # 2.2 触发策略 on_bar 回调
            for sym, bar in current_bar_map.items():
                self.strategy.on_bar(bar)

            # 2.3 提取并撮合策略下发的待处理订单
            pending_orders = self.strategy.extract_pending_orders()
            for order in pending_orders:
                if order.symbol in current_bar_map:
                    cur_price = current_bar_map[order.symbol].close
                    trade = self.broker.match_order(order, cur_price, self.portfolio, ts)
                    self.strategy.on_order_update(order)
                    if trade:
                        self.strategy.on_trade(trade)

            # 2.4 日终结算 (检查是否到达当日最后一根切片或回测尾声)
            first_bar = next(iter(current_bar_map.values()))
            cur_date_str = first_bar.date_str
            is_last_step = (idx == num_steps - 1)
            
            is_day_end = is_last_step
            if not is_last_step:
                next_ts = sorted_timestamps[idx + 1]
                next_date_str = next(iter(bars_by_ts[next_ts].values())).date_str
                if next_date_str != cur_date_str:
                    is_day_end = True

            if is_day_end:
                for pos in self.portfolio.positions.values():
                    pos.settle_day_end()

                daily_records.append({
                    "date": cur_date_str,
                    "timestamp": ts,
                    "cash": self.portfolio.cash,
                    "market_value": self.portfolio.total_market_value,
                    "total_equity": self.portfolio.total_equity
                })

        self.strategy.on_stop()

        # 3. 计算综合业绩指标
        result = PerformanceAnalytics.calculate(
            initial_cash=self.initial_cash,
            daily_records=daily_records,
            trades=self.portfolio.trades
        )
        return result
