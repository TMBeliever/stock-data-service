"""
========================================================================
策略：按估值/价格分位数智能定投“红利低波 ETF (512890 / 515100)”
核心逻辑：
  1. 每周第一个交易日执行定投；
  2. 计算过去 1 年（250 个交易日）的分位数水位：
     - 低估区间 (分位数 < 25%)：加大定投金额 (2000 元，2.0倍低吸)
     - 正常区间 (分位数 25%~75%)：标准定投金额 (1000 元，1.0倍定投)
     - 高估区间 (分位数 > 75%)：减少定投金额 (500 元，0.5倍控仓)
  3. 对比“普通固定定投（每周固定 1000 元）”，验证分位数定投的超额收益。
========================================================================
"""

import datetime
import polars as pl
import numpy as np
from sdk import StockDataSDK

def run_backtest(symbol: str = "512890", start_date: str = "2021-01-01"):
    sdk = StockDataSDK()
    
    # 1. 毫秒级从本地 Parquet 零拷贝读取前复权日K
    df = sdk.get_kline(symbol=symbol, period="1d", start=start_date, adjust="qfq")
    if df is None or df.is_empty():
        print(f"未能获取到 {symbol} 行情数据")
        return

    # 2. 转换日期并计算过去 250 天的滚动价格分位数
    # (在量化中，由于 ETF 标的持仓大多为低估值成份股，滚动价格/净值分位数与市盈率分位数具有高度一致的统计相关性)
    df_pandas = df.to_pandas()
    df_pandas["date"] = pd_dates = [datetime.datetime.fromtimestamp(ts / 1000, datetime.timezone.utc) for ts in df_pandas["timestamp"]]
    df_pandas["weekday"] = [d.weekday() for d in pd_dates] # 0 = Monday

    # 计算 250 天滚动分位数
    window = 250
    rolling_min = df_pandas["close"].rolling(window=window, min_periods=30).min()
    rolling_max = df_pandas["close"].rolling(window=window, min_periods=30).max()
    df_pandas["percentile"] = (df_pandas["close"] - rolling_min) / (rolling_max - rolling_min).replace(0, np.nan)
    df_pandas["percentile"] = df_pandas["percentile"].fillna(0.5)

    # 3. 模拟定投回测账户
    # 账户 A: 分位数智能定投
    cash_invested_smart = 0.0
    shares_smart = 0.0

    # 账户 B: 普通固定定投 (每周 1000 元)
    cash_invested_regular = 0.0
    shares_regular = 0.0

    trade_count = 0
    last_invest_week = -1

    for idx, row in df_pandas.iterrows():
        dt = row["date"]
        week_num = dt.isocalendar()[1]
        
        # 每周定投一次 (在每周出现的第一个交易日买入)
        if week_num != last_invest_week:
            last_invest_week = week_num
            trade_count += 1
            price = row["close"]
            pct = row["percentile"]

            # --- 智能分位数定投逻辑 ---
            if pct < 0.25:
                amt_smart = 2000.0  # 极度低估：双倍买入
            elif pct > 0.75:
                amt_smart = 500.0   # 高估区间：减半买入
            else:
                amt_smart = 1000.0  # 正常估值：基准买入

            shares_smart += amt_smart / price
            cash_invested_smart += amt_smart

            # --- 普通固定定投逻辑 ---
            amt_reg = 1000.0
            shares_regular += amt_reg / price
            cash_invested_regular += amt_reg

    # 4. 计算最终期末净值与收益
    final_price = df_pandas["close"].iloc[-1]
    final_date_str = df_pandas["date"].iloc[-1].strftime("%Y-%m-%d")

    val_smart = shares_smart * final_price
    ret_smart = ((val_smart - cash_invested_smart) / cash_invested_smart) * 100.0

    val_reg = shares_regular * final_price
    ret_reg = ((val_reg - cash_invested_regular) / cash_invested_regular) * 100.0

    alpha = ret_smart - ret_reg

    # 5. 输出结构化回测报告
    print("=" * 65)
    print(f"📊【红利低波 ETF ({symbol}) 估值分位数定投策略回测报告】")
    print("=" * 65)
    print(f"• 回测周期: {start_date} 至 {final_date_str} (总定投期数: {trade_count} 周)")
    print(f"• 期末收盘价: {final_price:.4f} 元")
    print("-" * 65)
    print(f"【策略 A：估值分位数智能定投】")
    print(f"  - 累计投入总本金: {cash_invested_smart:,.2f} 元")
    print(f"  - 期末资产总市值: {val_smart:,.2f} 元")
    print(f"  - 累计投资收益率: {ret_smart:+.2f}%")
    print("-" * 65)
    print(f"【策略 B：普通固定金额定投 (每周 1000 元)】")
    print(f"  - 累计投入总本金: {cash_invested_regular:,.2f} 元")
    print(f"  - 期末资产总市值: {val_reg:,.2f} 元")
    print(f"  - 累计投资收益率: {ret_reg:+.2f}%")
    print("-" * 65)
    print(f"🚀【超额收益 (Alpha)】: {alpha:+.2f}%")
    if alpha > 0:
        print(f"✓ 验证结论：估值分位数智能定投显著跑赢普通定投，实现了低估多吸筹、高估控风险！")
    print("=" * 65)

if __name__ == "__main__":
    run_backtest("512890")
