import sys
import argparse
from quant_core.client.data_client import data_client
from quant_core.backtest.broker import SimulatedBroker
from quant_core.backtest.engine import BacktestEngine
from quant_core.strategies.moving_average_cross import DualMovingAverageStrategy
from quant_core.strategies.dividend_etf_rebalance import DividendETFRebalanceStrategy
from quant_core.strategies.dividend_dca import SmartDividendDCAStrategy
from quant_core.strategies.buy_and_hold import BuyAndHoldStrategy
from quant_core.strategies.extreme_dip_heavy import ExtremeDipHeavyStrategy
from quant_core.strategies.dynamic_rebalance import DynamicRebalanceStrategy

def create_broker():
    """真实券商低费率撮合器 (万0.8 免5, ETF免印花税)"""
    return SimulatedBroker(
        slippage_pct=0.0005,        # 万5 滑点
        commission_rate=0.00008,    # 万0.8 佣金 (0.008%)
        min_commission=0.0,         # 免5 (0元起征)
        stamp_tax_rate=0.0,         # ETF 免印花税
        t_plus_one=True
    )

def main():
    parser = argparse.ArgumentParser(description="Run quantitative strategy backtest")
    parser.add_argument("--symbol", type=str, default="512890.SH.ETF", help="Target symbol (e.g. 512890.SH.ETF, 510300.SH.ETF, 513100.SH.ETF)")
    parser.add_argument(
        "--strategy",
        type=str,
        default="compare",
        choices=["ma", "dividend", "dca", "all_in", "dip_heavy", "rebalance", "compare"],
        help="Strategy type (compare: 四大核心策略横向对比)"
    )
    parser.add_argument("--start", type=str, default="2019-01-01", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, default=None, help="End date (YYYY-MM-DD, 留空则自动回测到最新交易日)")
    parser.add_argument("--cash", type=float, default=100_000.0, help="Initial cash (账户初始本金池)")
    parser.add_argument("--base-amount", type=float, default=1000.0, help="DCA base investment amount per period (每期定投基准金额，默认1000元)")
    parser.add_argument("--take-profit", action="store_true", default=False, help="开启泡沫区主动阶梯止盈 (默认关闭以避免慢牛行情中卖飞筹码)")
    args = parser.parse_args()

    print(f"[*] Fetching historical K-lines for {args.symbol} from {args.start} to {args.end or 'latest'} (QFQ 前复权)...")
    bars = data_client.get_bars(symbol=args.symbol, period="1d", start=args.start, end=args.end, adjust="qfq")
    
    if not bars:
        print(f"[!] Warning: No bars fetched for {args.symbol}. Please check stock-data service or symbol validity.")
        sys.exit(1)

    print(f"[+] Loaded {len(bars)} trading bars. [首日前复权收盘价: {bars[0].close:.4f} 元 | 最新日收盘价: {bars[-1].close:.4f} 元]")

    if args.strategy == "compare":
        # -------------------------------------------------------------
        # 四大核心策略多维对比回测
        # 1. 一次性买入死拿 (All-In)
        # 2. 经典价值定投 (Smart DCA)
        # 3. 极端低谷一击打满 (Extreme Dip Heavy)
        # 4. 动态恒定比例再平衡 (Dynamic Rebalance 85/15)
        # -------------------------------------------------------------
        print("\n" + "=" * 62)
        print("         >>> 1. 执行 一次性全仓买入死拿 (All-In) <<<")
        print("=" * 62)
        strat_allin = BuyAndHoldStrategy(target_pct=0.99)
        broker_allin = create_broker()
        engine_allin = BacktestEngine(strategy=strat_allin, broker=broker_allin, initial_cash=args.cash)
        res_allin = engine_allin.run({args.symbol: bars})
        res_allin.print_summary()
        comm_allin = sum(t.commission for t in engine_allin.portfolio.trades)

        print("\n" + "=" * 62)
        print("         >>> 2. 执行 经典智能估值定投 (Smart DCA) <<<")
        print("=" * 62)
        strat_dca = SmartDividendDCAStrategy(base_amount=args.base_amount, window=250, enable_take_profit=args.take_profit)
        broker_dca = create_broker()
        engine_dca = BacktestEngine(strategy=strat_dca, broker=broker_dca, initial_cash=args.cash)
        res_dca = engine_dca.run({args.symbol: bars})
        res_dca.print_summary()
        comm_dca = sum(t.commission for t in engine_dca.portfolio.trades)

        print("\n" + "=" * 62)
        print("         >>> 3. 执行 暴跌黄金坑一击打满 (Extreme Dip Heavy) <<<")
        print("=" * 62)
        strat_dip = ExtremeDipHeavyStrategy(ma_period=120, dip_threshold=0.20, defensive_pct=0.20)
        broker_dip = create_broker()
        engine_dip = BacktestEngine(strategy=strat_dip, broker=broker_dip, initial_cash=args.cash)
        res_dip = engine_dip.run({args.symbol: bars})
        res_dip.print_summary()
        comm_dip = sum(t.commission for t in engine_dip.portfolio.trades)

        print("\n" + "=" * 62)
        print("         >>> 4. 执行 自适应动态再平衡 (Dynamic Rebalance 85/15) <<<")
        print("=" * 62)
        strat_reb = DynamicRebalanceStrategy(target_pct=0.85, rebalance_band=0.05, check_interval=5)
        broker_reb = create_broker()
        engine_reb = BacktestEngine(strategy=strat_reb, broker=broker_reb, initial_cash=args.cash)
        res_reb = engine_reb.run({args.symbol: bars})
        res_reb.print_summary()
        comm_reb = sum(t.commission for t in engine_reb.portfolio.trades)

        # 打印综合对比表
        print("\n" + "=" * 90)
        print("                     【四大核心量化策略多维绩效横向终极大对比】")
        print("=" * 90)
        col_fmt = "{:<20} | {:>14} | {:>14} | {:>16} | {:>16}"
        print(col_fmt.format("指标项目", "1.死拿 (All-In)", "2.智能定投", "3.黄金坑打满", "4.动态再平衡(85/15)"))
        print("-" * 90)
        print(col_fmt.format("初始本金池", f"{res_allin.initial_cash:,.0f} 元", f"{res_dca.initial_cash:,.0f} 元", f"{res_dip.initial_cash:,.0f} 元", f"{res_reb.initial_cash:,.0f} 元"))
        print(col_fmt.format("期末账户总资产", f"{res_allin.final_equity:,.2f} 元", f"{res_dca.final_equity:,.2f} 元", f"{res_dip.final_equity:,.2f} 元", f"{res_reb.final_equity:,.2f} 元"))
        print(col_fmt.format("累计净收益额", f"{res_allin.final_equity - res_allin.initial_cash:,.2f} 元", f"{res_dca.final_equity - res_dca.initial_cash:,.2f} 元", f"{res_dip.final_equity - res_dip.initial_cash:,.2f} 元", f"{res_reb.final_equity - res_reb.initial_cash:,.2f} 元"))
        print(col_fmt.format("累计总收益率", f"{res_allin.total_return*100:.2f} %", f"{res_dca.total_return*100:.2f} %", f"{res_dip.total_return*100:.2f} %", f"{res_reb.total_return*100:.2f} %"))
        print(col_fmt.format("年化复合收益(CAGR)", f"{res_allin.annualized_return*100:.2f} %", f"{res_dca.annualized_return*100:.2f} %", f"{res_dip.annualized_return*100:.2f} %", f"{res_reb.annualized_return*100:.2f} %"))
        print(col_fmt.format("最大历史回撤(MaxDD)", f"{res_allin.max_drawdown*100:.2f} %", f"{res_dca.max_drawdown*100:.2f} %", f"{res_dip.max_drawdown*100:.2f} %", f"{res_reb.max_drawdown*100:.2f} %"))
        print(col_fmt.format("夏普比率(Sharpe)", f"{res_allin.sharpe_ratio:.2f}", f"{res_dca.sharpe_ratio:.2f}", f"{res_dip.sharpe_ratio:.2f}", f"{res_reb.sharpe_ratio:.2f}"))
        print(col_fmt.format("卡玛比率(Calmar)", f"{res_allin.calmar_ratio:.2f}", f"{res_dca.calmar_ratio:.2f}", f"{res_dip.calmar_ratio:.2f}", f"{res_reb.calmar_ratio:.2f}"))
        print(col_fmt.format("交易总笔数", f"{res_allin.total_trades} 笔", f"{res_dca.total_trades} 笔", f"{res_dip.total_trades} 笔", f"{res_reb.total_trades} 笔"))
        print(col_fmt.format("累计手续费(万0.8)", f"{comm_allin:.2f} 元", f"{comm_dca:.2f} 元", f"{comm_dip:.2f} 元", f"{comm_reb:.2f} 元"))
        print("=" * 90 + "\n")
        return

    if args.strategy == "ma":
        strat = DualMovingAverageStrategy(fast_period=5, slow_period=20)
    elif args.strategy == "dividend":
        strat = DividendETFRebalanceStrategy(window=120)
    elif args.strategy == "dca":
        strat = SmartDividendDCAStrategy(base_amount=args.base_amount, window=250, enable_take_profit=args.take_profit)
    elif args.strategy == "all_in":
        strat = BuyAndHoldStrategy(target_pct=0.99)
    elif args.strategy == "dip_heavy":
        strat = ExtremeDipHeavyStrategy(ma_period=120, dip_threshold=0.20, defensive_pct=0.20)
    elif args.strategy == "rebalance":
        strat = DynamicRebalanceStrategy(target_pct=0.85, rebalance_band=0.05, check_interval=5)
    else:
        strat = BuyAndHoldStrategy()

    broker = create_broker()
    engine = BacktestEngine(strategy=strat, broker=broker, initial_cash=args.cash)
    print(f"[*] Executing backtest: {strat.name} on {args.symbol}...")
    result = engine.run({args.symbol: bars})

    result.print_summary()

if __name__ == "__main__":
    main()
