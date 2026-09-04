import datetime
from typing import List, Optional
import polars as pl
import pandas as pd
import yfinance as yf
from adapters.base import BaseDataSource
from core.models import SymbolInfo, KlinePeriod, AssetType, Market

class YFinanceAdapter(BaseDataSource):
    """美股、港股及全球核心宽基指数/ETF 适配器 (基于 yfinance 真实数据)"""

    def _convert_ticker_for_yf(self, info: SymbolInfo) -> str:
        ticker = info.ticker
        if info.market == Market.US:
            if info.asset_type == AssetType.INDEX:
                # 常见指数映射
                mapping = {"SPX": "^GSPC", "NDX": "^NDX", "DJI": "^DJI", "VIX": "^VIX"}
                return mapping.get(ticker, f"^{ticker}")
            return ticker # 如 AAPL, SPY
        elif info.market == Market.HK:
            if info.asset_type == AssetType.INDEX:
                return "^HSI" if ticker == "HSI" else f"^{ticker}"
            # 港股在 yf 格式为 0700.HK 或 9988.HK (去前置0或4位)
            clean_ticker = ticker.lstrip("0")
            if len(clean_ticker) < 4:
                clean_ticker = clean_ticker.zfill(4)
            return f"{clean_ticker}.HK"
        return ticker

    def fetch_daily(self, info: SymbolInfo, start_date: str, end_date: str) -> Optional[pl.DataFrame]:
        yf_ticker = self._convert_ticker_for_yf(info)
        try:
            # 获取原始行情 (不自动复权，保留原始价格)
            t = yf.Ticker(yf_ticker)
            # yfinance 的 end 参数在底层是开区间 [start, end)，顺延一天以闭区间包含 end_date 当天
            try:
                end_dt = datetime.datetime.strptime(end_date, "%Y-%m-%d") + datetime.timedelta(days=1)
                yf_end_date = end_dt.strftime("%Y-%m-%d")
            except Exception:
                yf_end_date = end_date

            df_raw = t.history(start=start_date, end=yf_end_date, interval="1d", auto_adjust=False)
            
            if df_raw is None or df_raw.empty:
                return None

            # 转换为 UTC 毫秒时间戳
            timestamps = []
            for dt_idx in df_raw.index:
                # yf index 是带时区的 DatetimeIndex
                if dt_idx.tzinfo is not None:
                    utc_dt = dt_idx.tz_convert("UTC")
                else:
                    utc_dt = dt_idx.tz_localize("UTC")
                timestamps.append(int(utc_dt.timestamp() * 1000))

            factors = (df_raw["Adj Close"] / df_raw["Close"]).fillna(1.0).astype(float) if "Adj Close" in df_raw.columns else [1.0] * len(df_raw)

            pldf = pl.DataFrame({
                "timestamp": pl.Series(timestamps, dtype=pl.Int64),
                "open": pl.Series(df_raw["Open"].astype(float), dtype=pl.Float32),
                "high": pl.Series(df_raw["High"].astype(float), dtype=pl.Float32),
                "low": pl.Series(df_raw["Low"].astype(float), dtype=pl.Float32),
                "close": pl.Series(df_raw["Close"].astype(float), dtype=pl.Float32),
                "volume": pl.Series(df_raw["Volume"].astype(float), dtype=pl.Float64),
                "amount": pl.Series([0.0] * len(df_raw), dtype=pl.Float64),
                "factor": pl.Series(factors, dtype=pl.Float32),
                "nav": pl.Series([None] * len(df_raw), dtype=pl.Float32)
            })

            return pldf.sort("timestamp")
        except Exception as e:
            print(f"[YFinanceAdapter] Error fetching daily for {info.symbol} ({yf_ticker}): {e}")
            return None

    def fetch_minute(self, info: SymbolInfo, period: KlinePeriod, start_date: str, end_date: str) -> Optional[pl.DataFrame]:
        yf_ticker = self._convert_ticker_for_yf(info)
        try:
            t = yf.Ticker(yf_ticker)
            interval_map = {
                KlinePeriod.M1: "1m",
                KlinePeriod.M5: "5m",
                KlinePeriod.M15: "15m",
                KlinePeriod.M30: "30m",
                KlinePeriod.M60: "60m",
            }
            yf_interval = interval_map.get(period, "1m")
            try:
                end_dt = datetime.datetime.strptime(end_date, "%Y-%m-%d") + datetime.timedelta(days=1)
                yf_end_date = end_dt.strftime("%Y-%m-%d")
            except Exception:
                yf_end_date = end_date

            df_raw = t.history(start=start_date, end=yf_end_date, interval=yf_interval, auto_adjust=False)

            if df_raw is None or df_raw.empty:
                return None

            timestamps = []
            for dt_idx in df_raw.index:
                if dt_idx.tzinfo is not None:
                    utc_dt = dt_idx.tz_convert("UTC")
                else:
                    utc_dt = dt_idx.tz_localize("UTC")
                timestamps.append(int(utc_dt.timestamp() * 1000))

            pldf = pl.DataFrame({
                "timestamp": pl.Series(timestamps, dtype=pl.Int64),
                "open": pl.Series(df_raw["Open"].astype(float), dtype=pl.Float32),
                "high": pl.Series(df_raw["High"].astype(float), dtype=pl.Float32),
                "low": pl.Series(df_raw["Low"].astype(float), dtype=pl.Float32),
                "close": pl.Series(df_raw["Close"].astype(float), dtype=pl.Float32),
                "volume": pl.Series(df_raw["Volume"].astype(float), dtype=pl.Float64),
                "amount": pl.Series([0.0] * len(df_raw), dtype=pl.Float64),
                "factor": pl.Series([1.0] * len(df_raw), dtype=pl.Float32),
                "nav": pl.Series([None] * len(df_raw), dtype=pl.Float32)
            })

            return pldf.sort("timestamp")
        except Exception as e:
            print(f"[YFinanceAdapter] Error fetching minute for {info.symbol}: {e}")
            return None

    def fetch_snapshot(self, market: str) -> Optional[pl.DataFrame]:
        # yfinance 无统一全市场快照接口，针对美股返回主要大盘股快照
        return None

    def fetch_calendar(self, market: str, year: int) -> List[dict]:
        # 美股/港股日历可通过拉取标普/恒指历史交易日提取
        idx_sym = "^GSPC" if market == "US" else "^HSI"
        try:
            t = yf.Ticker(idx_sym)
            hist = t.history(start=f"{year}-01-01", end=f"{year}-12-31", interval="1d")
            results = []
            for dt in hist.index:
                d_str = dt.strftime("%Y-%m-%d")
                results.append({"market": market, "trade_date": d_str, "is_open": True})
            return results
        except Exception as e:
            print(f"[YFinanceAdapter] Error fetching calendar: {e}")
            return []

    def fetch_symbols(self, market: str) -> List[SymbolInfo]:
        # 返回核心基准指数和最知名标的
        if market == "US":
            return [
                SymbolInfo(symbol="AAPL.US.STK", ticker="AAPL", market=Market.US, asset_type=AssetType.STOCK, name="Apple Inc.", currency="USD"),
                SymbolInfo(symbol="MSFT.US.STK", ticker="MSFT", market=Market.US, asset_type=AssetType.STOCK, name="Microsoft Corp.", currency="USD"),
                SymbolInfo(symbol="NVDA.US.STK", ticker="NVDA", market=Market.US, asset_type=AssetType.STOCK, name="NVIDIA Corp.", currency="USD"),
                SymbolInfo(symbol="SPX.US.IDX", ticker="SPX", market=Market.US, asset_type=AssetType.INDEX, name="S&P 500 Index", currency="USD", is_benchmark=True),
                SymbolInfo(symbol="NDX.US.IDX", ticker="NDX", market=Market.US, asset_type=AssetType.INDEX, name="NASDAQ 100 Index", currency="USD", is_benchmark=True),
                SymbolInfo(symbol="SPY.US.ETF", ticker="SPY", market=Market.US, asset_type=AssetType.ETF, name="SPDR S&P 500 ETF", currency="USD", is_benchmark=True),
                SymbolInfo(symbol="QQQ.US.ETF", ticker="QQQ", market=Market.US, asset_type=AssetType.ETF, name="Invesco QQQ Trust", currency="USD", is_benchmark=True),
            ]
        elif market == "HK":
            return [
                SymbolInfo(symbol="00700.HK.STK", ticker="00700", market=Market.HK, asset_type=AssetType.STOCK, name="腾讯控股", currency="HKD"),
                SymbolInfo(symbol="09988.HK.STK", ticker="09988", market=Market.HK, asset_type=AssetType.STOCK, name="阿里巴巴-SW", currency="HKD"),
                SymbolInfo(symbol="HSI.HK.IDX", ticker="HSI", market=Market.HK, asset_type=AssetType.INDEX, name="恒生指数", currency="HKD", is_benchmark=True),
                SymbolInfo(symbol="02800.HK.ETF", ticker="02800", market=Market.HK, asset_type=AssetType.ETF, name="盈富基金", currency="HKD", is_benchmark=True),
            ]
        return []
