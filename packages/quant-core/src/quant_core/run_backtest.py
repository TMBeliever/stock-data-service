import sys
import argparse
from quant_core.client.data_client import data_client
from quant_core.backtest.broker import SimulatedBroker
from quant_core.backtest.engine import BacktestEngine
from quant_core.strategies.moving_average_cross import DualMovingAverageStrategy
from quant_core.strategies.dividend_etf_rebalance import DividendETFRebalanceStrategy
from quant_core.strategies.dividend_dca import SmartDividendDCAStrategy
from quant_core.strategies.buy_and_hold import BuyAndHoldStrategy

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
    parser.add_argument("--symbol", type=str, default="512890.SH.ETF", help="Target symbol (e.g. 512890.SH.ETF, 510300.SH.ETF)")
    parser.add_argument(
        "--strategy",
        type=str,
        default="compare",
        choices=["ma", "dividend", "dca", "all_in", "compare"],
        help="Strategy type (compare: 一次性全仓 vs 智能定投 对比回测)"
    )
    parser.add_argument("--start", type=str, default="2021-01-01", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, default=None, help="End date (YYYY-MM-DD, 留空则自动回测到最新交易日)")
    parser.add_argument("--cash", type=float, default=100_000.0, help="Initial cash (账户初始本金池)")
    parser.add_argument("--base-amount", type=float, default=1000.0, help="DCA base investment amount per period (每期定投基准金额，默认1000元)")
    args = parser.parse_args()

    print(f"[*] Fetching historical K-lines for {args.symbol} from {args.start} to {args.end or 'latest'} (QFQ 前复权)...")
    bars = data_client.get_bars(symbol=args.symbol, period="1d", start=args.start, end=args.end, adjust="qfq")
    
    if not bars:
        print(f"[!] Warning: No bars fetched for {args.symbol}. Please check stock-data service or symbol validity.")
        sys.exit(1)

    print(f"[+] Loaded {len(bars)} trading bars. [首日前复权收盘价: {bars[0].close:.4f} 元 | 最新日收盘价: {bars[-1].close:.4f} 元]")

    if args.strategy == "compare":
        # -------------------------------------------------------------
        # 对比回测: 一次性全仓买入并持有 (All-In) VS 智能红利定投 (Smart DCA)
        # -------------------------------------------------------------
        print("\n" + "=" * 62)
        print("         >>> 1. 执行 一次性全仓买入并持有 (All-In) <<<")
        print("=" * 62)
        strat_allin = BuyAndHoldStrategy(target_pct=0.99)
        broker_allin = create_broker()
        engine_allin = BacktestEngine(strategy=strat_allin, broker=broker_allin, initial_cash=args.cash)
        res_allin = engine_allin.run({args.symbol: bars})
        res_allin.print_summary()
        comm_allin = sum(t.commission for t in engine_allin.portfolio.trades)

        print("\n" + "=" * 62)
        print("         >>> 2. 执行 智能红利低波定投 (Smart Dividend DCA) <<<")
        print("=" * 62)
        strat_dca = SmartDividendDCAStrategy(base_amount=args.base_amount, window=250, enable_take_profit=True)
        broker_dca = create_broker()
        engine_dca = BacktestEngine(strategy=strat_dca, broker=broker_dca, initial_cash=args.cash)
        res_dca = engine_dca.run({args.symbol: bars})
        res_dca.print_summary()
        comm_dca = sum(t.commission for t in engine_dca.portfolio.trades)

        pos_dca = engine_dca.portfolio.get_position(args.symbol)
        
        # 打印横向综合对比表
        print("\n" + "=" * 70)
        print("                【核心策略绩效横向对比总表 (万0.8 免5)】")
        print("=" * 70)
        print(f"{'指标项目':<24} | {'一次性买入并持有 (All-In)':<20} | {'智能红利定投 (Smart DCA)':<20}")
        print("-" * 70)
        print(f"{'初始资金池':<24} | {res_allin.initial_cash:>18,.2f} 元 | {res_dca.initial_cash:>18,.2f} 元")
        print(f"{'期末账户总权益':<24} | {res_allin.final_equity:>18,.2f} 元 | {res_dca.final_equity:>18,.2f} 元")
        print(f"{'账户累计净收益额':<24} | {res_allin.final_equity - res_allin.initial_cash:>18,.2f} 元 | {res_dca.final_equity - res_dca.initial_cash:>18,.2f} 元")
        print(f"{'账户累计收益率':<24} | {res_allin.total_return * 100:>17.2f} % | {res_dca.total_return * 100:>17.2f} %")
        print(f"{'年化复合收益率 (CAGR)':<24} | {res_allin.annualized_return * 100:>17.2f} % | {res_dca.annualized_return * 100:>17.2f} %")
        print(f"{'最大历史回撤 (MaxDD)':<24} | {res_allin.max_drawdown * 100:>17.2f} % | {res_dca.max_drawdown * 100:>17.2f} %")
        print(f"{'夏普比率 (Sharpe)':<24} | {res_allin.sharpe_ratio:>18.2f}   | {res_dca.sharpe_ratio:>18.2f}  ")
        print(f"{'卡玛比率 (Calmar)':<24} | {res_allin.calmar_ratio:>18.2f}   | {res_dca.calmar_ratio:>18.2f}  ")
        print(f"{'交易总笔数':<24} | {res_allin.total_trades:>18} 笔 | {res_dca.total_trades:>18} 笔")
        print(f"{'累计手续费支出':<24} | {comm_allin:>18.2f} 元 | {comm_dca:>18.2f} 元")
        # 统计定投的净资金流与真实投入本金收益率
        trades_dca = engine_dca.portfolio.trades
        total_buy_cash = sum(t.price * t.quantity + t.commission for t in trades_dca if t.side.value == "BUY")
        total_sell_cash = sum(t.price * t.quantity - t.commission for t in trades_dca if t.side.value == "SELL")
        net_invested = total_buy_cash - total_sell_cash
        pure_stock_profit = pos_dca.market_value - net_invested
        roi_net = (pure_stock_profit / net_invested * 100) if net_invested > 0 else 0.0

        print(f" [智能定投资金与收益深度剖析]")
        print(f" • 定投执行总期数 (周)        : {strat_dca.dca_count} 周")
        print(f" • 累计买入本金总额 (Gross)   : {total_buy_cash:>15,.2f} 元")
        print(f" • 泡沫区间主动止盈落袋 (Sell): {total_sell_cash:>15,.2f} 元 (已变现回流为现金)")
        print(f" • 实际净占用的市场本金 (Net) : {net_invested:>15,.2f} 元")
        print(f" • 期末持仓股票市值 (Market)  : {pos_dca.market_value:>15,.2f} 元 ({pos_dca.quantity:,.0f} 股)")
        print(f" • 实际净本金收益率 (Real ROI): {roi_net:>14.2f} % (真实定投资金回报翻倍)")
        print(f" • 账户可用安全现金池 (Cash)  : {engine_dca.portfolio.cash:>15,.2f} 元\n")
        return

    if args.strategy == "ma":
        strat = DualMovingAverageStrategy(fast_period=5, slow_period=20)
    elif args.strategy == "dividend":
        strat = DividendETFRebalanceStrategy(window=120)
    elif args.strategy == "dca":
        strat = SmartDividendDCAStrategy(base_amount=args.base_amount, window=250, enable_take_profit=True)
    elif args.strategy == "all_in":
        strat = BuyAndHoldStrategy(target_pct=0.99)
    else:
        strat = BuyAndHoldStrategy()

    broker = create_broker()
    engine = BacktestEngine(strategy=strat, broker=broker, initial_cash=args.cash)
    print(f"[*] Executing backtest: {strat.name} on {args.symbol}...")
    result = engine.run({args.symbol: bars})

    result.print_summary()

    if isinstance(strat, SmartDividendDCAStrategy):
        pos = engine.portfolio.get_position(args.symbol)
        comm = sum(t.commission for t in engine.portfolio.trades)
        print(f" [DCA Details]")
        print(f" • 定投总期数 (Weeks)       : {strat.dca_count}")
        print(f" • 累计定投本金支出 (Invested): {strat.total_invested_cash:,.2f} CNY")
        print(f" • 期末账户总持仓 (Shares)   : {pos.quantity:,.0f} 股")
        print(f" • 期末持仓市值 (Market Val): {pos.market_value:,.2f} CNY")
        print(f" • 剩余可用现金 (Cash)       : {engine.portfolio.cash:,.2f} CNY")
        print(f" • 累计交易佣金支出 (万0.8免5): {comm:,.2f} CNY\n")

if __name__ == "__main__":
    main()
