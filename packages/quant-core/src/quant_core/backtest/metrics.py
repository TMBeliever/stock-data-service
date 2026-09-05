import math
from typing import List, Dict, Any
from pydantic import BaseModel
import numpy as np

class BacktestResult(BaseModel):
    initial_cash: float
    final_equity: float
    total_return: float
    annualized_return: float
    max_drawdown: float
    sharpe_ratio: float
    sortino_ratio: float
    calmar_ratio: float
    win_rate: float
    profit_factor: float
    total_trades: int
    daily_records: List[Dict[str, Any]] = []
    warnings: List[str] = []
    rejected_orders: List[Dict[str, Any]] = []

    def print_summary(self):
        """打印标准量化绩效报表"""
        print("\n" + "=" * 62)
        print("                 量化策略回测绩效分析报告")
        print("=" * 62)
        print(f" 初始资金 (Initial Cash)        : {self.initial_cash:>15,.2f} CNY")
        print(f" 期末资产 (Final Equity)        : {self.final_equity:>15,.2f} CNY")
        print(f" 累计收益率 (Total Return)       : {self.total_return * 100:>14.2f} %")
        print(f" 年化收益率 (CAGR)               : {self.annualized_return * 100:>14.2f} %")
        print(f" 最大回撤 (Max Drawdown)        : {self.max_drawdown * 100:>14.2f} %")
        print(f" 夏普比率 (Sharpe Ratio, rf=2%) : {self.sharpe_ratio:>15.2f}")
        print(f" 索提诺比率 (Sortino Ratio)     : {self.sortino_ratio:>15.2f}")
        print(f" 卡玛比率 (Calmar Ratio)        : {self.calmar_ratio:>15.2f}")
        print(f" 交易总笔数 (Total Trades)       : {self.total_trades:>15d}")
        print(f" 胜率 (Win Rate)                 : {self.win_rate * 100:>14.2f} %")
        print(f" 盈亏比 (Profit Factor)          : {self.profit_factor:>15.2f}")
        print("=" * 62 + "\n")

class PerformanceAnalytics:
    """绩效评估指标计算引擎"""
    @staticmethod
    def calculate(
        initial_cash: float,
        daily_records: List[Dict[str, Any]],
        trades: list,
        risk_free_rate: float = 0.02
    ) -> BacktestResult:
        if not daily_records:
            return BacktestResult(
                initial_cash=initial_cash,
                final_equity=initial_cash,
                total_return=0.0,
                annualized_return=0.0,
                max_drawdown=0.0,
                sharpe_ratio=0.0,
                sortino_ratio=0.0,
                calmar_ratio=0.0,
                win_rate=0.0,
                profit_factor=0.0,
                total_trades=0,
                daily_records=[]
            )

        equities = np.array([r["total_equity"] for r in daily_records])
        final_equity = float(equities[-1])
        total_return = (final_equity - initial_cash) / initial_cash

        # 交易日天数换算年化收益
        days = len(equities)
        trading_years = max(days / 250.0, 1.0 / 250.0)
        cagr = (1.0 + total_return) ** (1.0 / trading_years) - 1.0 if (1.0 + total_return) > 0 else -1.0

        # 最大回撤 (Max Drawdown)
        cummax = np.maximum.accumulate(equities)
        drawdowns = (cummax - equities) / np.where(cummax > 0, cummax, 1.0)
        max_drawdown = float(np.max(drawdowns)) if len(drawdowns) > 0 else 0.0

        # 日收益率序列
        daily_returns = np.diff(equities) / np.where(equities[:-1] > 0, equities[:-1], 1.0)
        
        # 夏普与索提诺比率
        rf_daily = risk_free_rate / 250.0
        excess_returns = daily_returns - rf_daily
        
        if len(daily_returns) > 1 and np.std(daily_returns) > 1e-8:
            sharpe = float(np.mean(excess_returns) / np.std(daily_returns) * math.sqrt(250.0))
        else:
            sharpe = 0.0

        # 下行波动率 (Downside deviation)
        downside = daily_returns[daily_returns < rf_daily]
        if len(downside) > 0 and np.std(downside) > 1e-8:
            sortino = float(np.mean(excess_returns) / np.std(downside) * math.sqrt(250.0))
        else:
            sortino = 0.0

        # 卡玛比率
        calmar = cagr / max_drawdown if max_drawdown > 1e-6 else 0.0

        # 基于成交流水 FIFO 配对计算胜率与盈亏比
        win_rate = 0.0
        profit_factor = 1.0
        buy_queues: Dict[str, list] = {}
        trade_pnls: list[float] = []

        for t in trades:
            sym = t.symbol
            if sym not in buy_queues:
                buy_queues[sym] = []
            if getattr(t.side, "value", str(t.side)) == "BUY":
                buy_queues[sym].append({"price": t.price, "qty": t.quantity, "comm": t.commission})
            else:
                sell_qty = t.quantity
                cost = 0.0
                while sell_qty > 0 and buy_queues[sym]:
                    b = buy_queues[sym][0]
                    matched_qty = min(sell_qty, b["qty"])
                    cost += b["price"] * matched_qty + (b["comm"] * (matched_qty / b["qty"]) if b["qty"] > 0 else 0)
                    b["qty"] -= matched_qty
                    sell_qty -= matched_qty
                    if b["qty"] <= 1e-6:
                        buy_queues[sym].pop(0)
                proceeds = t.price * t.quantity - t.commission - t.tax
                trade_pnls.append(proceeds - cost)

        if trade_pnls:
            wins = [p for p in trade_pnls if p > 0]
            losses = [abs(p) for p in trade_pnls if p < 0]
            win_rate = len(wins) / len(trade_pnls)
            sum_win = sum(wins)
            sum_loss = sum(losses)
            if sum_loss > 0:
                profit_factor = float(sum_win / sum_loss)
            elif sum_win > 0:
                profit_factor = 99.0
        elif len(daily_returns) > 0:
            win_rate = float(np.sum(daily_returns > 0) / len(daily_returns))

        return BacktestResult(
            initial_cash=initial_cash,
            final_equity=final_equity,
            total_return=total_return,
            annualized_return=cagr,
            max_drawdown=max_drawdown,
            sharpe_ratio=sharpe,
            sortino_ratio=sortino,
            calmar_ratio=calmar,
            win_rate=win_rate,
            profit_factor=profit_factor,
            total_trades=len(trades),
            daily_records=daily_records
        )
