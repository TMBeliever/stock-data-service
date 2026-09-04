import sys
import argparse
from quant_core.client.data_client import data_client
from quant_core.backtest.broker import SimulatedBroker
from quant_core.backtest.engine import BacktestEngine
from quant_core.strategies.moving_average_cross import DualMovingAverageStrategy
from quant_core.strategies.dividend_etf_rebalance import DividendETFRebalanceStrategy
from quant_core.strategies.dividend_dca import SmartDividendDCAStrategy

def main():
    parser = argparse.ArgumentParser(description="Run quantitative strategy backtest")
    parser.add_argument("--symbol", type=str, default="512890.SH.ETF", help="Target symbol (e.g. 512890.SH.ETF, 510300.SH.ETF)")
    parser.add_argument("--strategy", type=str, default="dca", choices=["ma", "dividend", "dca"], help="Strategy type")
    parser.add_argument("--start", type=str, default="2021-01-01", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, default=None, help="End date (YYYY-MM-DD, 留空则自动回测到最新交易日)")
    parser.add_argument("--cash", type=float, default=100_000.0, help="Initial cash (账户初始本金池)")
    parser.add_argument("--base-amount", type=float, default=1000.0, help="DCA base investment amount per period (每期定投基准金额，默认1000元)")
    args = parser.parse_args()

    print(f"[*] Fetching historical K-lines for {args.symbol} from {args.start} to {args.end}...")
    bars = data_client.get_bars(symbol=args.symbol, period="1d", start=args.start, end=args.end, adjust="qfq")
    
    if not bars:
        print(f"[!] Warning: No bars fetched for {args.symbol}. Please check stock-data service or symbol validity.")
        sys.exit(1)

    print(f"[+] Loaded {len(bars)} trading bars.")

    if args.strategy == "ma":
        strat = DualMovingAverageStrategy(fast_period=5, slow_period=20)
    elif args.strategy == "dividend":
        strat = DividendETFRebalanceStrategy(window=120)
    elif args.strategy == "dca":
        strat = SmartDividendDCAStrategy(base_amount=args.base_amount, window=250, enable_take_profit=True)
    else:
        strat = DualMovingAverageStrategy()

    broker = SimulatedBroker(
        slippage_pct=0.0005,
        commission_rate=0.00025,
        min_commission=5.0,
        stamp_tax_rate=0.0005,
        t_plus_one=True
    )

    engine = BacktestEngine(strategy=strat, broker=broker, initial_cash=args.cash)
    print(f"[*] Executing backtest: {strat.name} on {args.symbol}...")
    result = engine.run({args.symbol: bars})

    result.print_summary()

    if isinstance(strat, SmartDividendDCAStrategy):
        pos = engine.portfolio.get_position(args.symbol)
        print(f" [DCA Details]")
        print(f" • 定投总期数 (Weeks)       : {strat.dca_count}")
        print(f" • 累计定投本金支出 (Invested): {strat.total_invested_cash:,.2f} CNY")
        print(f" • 期末账户总持仓 (Shares)   : {pos.quantity:,.0f} 股")
        print(f" • 期末持仓市值 (Market Val): {pos.market_value:,.2f} CNY")
        print(f" • 剩余可用现金 (Cash)       : {engine.portfolio.cash:,.2f} CNY\n")

if __name__ == "__main__":
    main()
