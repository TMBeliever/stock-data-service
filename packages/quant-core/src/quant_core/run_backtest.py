import sys
import argparse
from quant_core.client.data_client import data_client
from quant_core.backtest.broker import SimulatedBroker
from quant_core.backtest.engine import BacktestEngine
from quant_core.strategies.moving_average_cross import DualMovingAverageStrategy
from quant_core.strategies.dividend_etf_rebalance import DividendETFRebalanceStrategy

def main():
    parser = argparse.ArgumentParser(description="Run quantitative strategy backtest")
    parser.add_argument("--symbol", type=str, default="510300.SH.ETF", help="Target symbol (e.g. 510300.SH.ETF, 600519.SH.STK)")
    parser.add_argument("--strategy", type=str, default="ma", choices=["ma", "dividend"], help="Strategy type")
    parser.add_argument("--start", type=str, default="2022-01-01", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, default="2024-01-01", help="End date (YYYY-MM-DD)")
    parser.add_argument("--cash", type=float, default=100_000.0, help="Initial cash")
    args = parser.parse_args()

    print(f"[*] Fetching historical K-lines for {args.symbol} from {args.start} to {args.end}...")
    bars = data_client.get_bars(symbol=args.symbol, period="1d", start=args.start, end=args.end, adjust="qfq")
    
    if not bars:
        print(f"[!] Warning: No bars fetched for {args.symbol}. Please check stock-data service or symbol validity.")
        sys.exit(1)

    print(f"[+] Loaded {len(bars)} trading bars.")

    if args.strategy == "ma":
        strat = DualMovingAverageStrategy(fast_period=5, slow_period=20)
    else:
        strat = DividendETFRebalanceStrategy(window=120)

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

if __name__ == "__main__":
    main()
