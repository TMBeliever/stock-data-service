import asyncio
import datetime
from typing import Optional, List
import polars as pl
import duckdb
from core.models import (
    KlinePeriod, AdjustType, parse_symbol, format_symbol, 
    SymbolInfo, Market, AssetType, SnapshotBatchResponse
)
from core.database import meta_db
from core.lock import single_flight
from storage.parquet_manager import parquet_mgr
from storage.compute import compute_engine

class StockDataSDK:
    """
    量化回测与分析直通 SDK：
    提供与 API 完全一致的 LazyLoad 与智能补齐逻辑，
    但直接在内存中返回 Polars DataFrame / Arrow，绕过 HTTP 序列化，性能提升 50 倍以上。
    """
    def __init__(self):
        self.meta_db = meta_db
        self.parquet_mgr = parquet_mgr
        self.compute = compute_engine

    async def get_kline_async(
        self,
        symbol: str,
        period: str = "1d",
        start: Optional[str] = None,
        end: Optional[str] = None,
        adjust: str = "raw",
        indicators: Optional[list[str]] = None,
        limit: Optional[int] = None
    ) -> Optional[pl.DataFrame]:
        """异步获取 K 线数据 (Polars DataFrame)"""
        ticker, market_str, type_str = parse_symbol(symbol)
        m = Market(market_str)
        t = AssetType(type_str)
        kline_period = KlinePeriod(period)
        adj_type = AdjustType(adjust)
        clean_symbol = format_symbol(ticker, market_str, type_str)

        # 补齐默认时间区间 (与 REST API 规范严格对称，杜绝未来函数和魔术硬编码日期)
        today_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
        if not end:
            end = today_str
        if not start:
            days = 365 if kline_period == KlinePeriod.D1 else 5
            start_dt = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)
            start = start_dt.strftime("%Y-%m-%d")

        if start > end:
            raise ValueError(f"Invalid date range: start date ({start}) cannot be later than end date ({end}).")

        # 1. 资产元数据对齐
        sym_record = self.meta_db.get_symbol(clean_symbol)
        if sym_record:
            info = SymbolInfo(
                symbol=clean_symbol,
                ticker=ticker,
                market=m,
                asset_type=t,
                name=sym_record["name"],
                currency=sym_record["currency"],
                is_benchmark=bool(sym_record["is_benchmark"])
            )
        else:
            is_bench = (t == AssetType.INDEX) or (ticker in ["SPY", "QQQ", "510300", "159915"])
            info = SymbolInfo(
                symbol=clean_symbol,
                ticker=ticker,
                market=m,
                asset_type=t,
                name=ticker,
                currency="USD" if m == Market.US else ("HKD" if m == Market.HK else "CNY"),
                is_benchmark=is_bench
            )
            self.meta_db.upsert_symbol(info)

        # 2. 防并发击穿与按需加载
        async with single_flight.acquire(clean_symbol):
            if kline_period in [KlinePeriod.M5, KlinePeriod.M15, KlinePeriod.M30, KlinePeriod.M60]:
                fetch_period = KlinePeriod.M1
            elif kline_period in [KlinePeriod.W1, KlinePeriod.MON1, KlinePeriod.Y1]:
                fetch_period = KlinePeriod.D1
            else:
                fetch_period = kline_period
            df = await self.parquet_mgr.get_or_fetch(info, fetch_period, start, end)

        if df is None or df.is_empty():
            return None

        # 3. 周期动态合成
        if kline_period in [KlinePeriod.M5, KlinePeriod.M15, KlinePeriod.M30, KlinePeriod.M60]:
            df = self.compute.resample_minutes(df, kline_period)
        elif kline_period in [KlinePeriod.W1, KlinePeriod.MON1, KlinePeriod.Y1]:
            df = self.compute.resample_higher_period(df, kline_period)

        # 4. 动态复权
        if adj_type != AdjustType.RAW:
            df = self.compute.apply_adjustment(df, adj_type)

        # 5. ETF 折溢价
        if t == AssetType.ETF:
            df = self.compute.calculate_etf_premium(df)

        # 6. 常用量化指标向量化计算
        if indicators:
            df = self.compute.compute_indicators(df, indicators)

        # 7. 数量上限截断
        if limit is not None and len(df) > limit:
            df = df.tail(limit)

        return df

    def get_kline(
        self,
        symbol: str,
        period: str = "1d",
        start: Optional[str] = None,
        end: Optional[str] = None,
        adjust: str = "raw",
        indicators: Optional[list[str]] = None,
        limit: Optional[int] = None
    ) -> Optional[pl.DataFrame]:
        """
        同步包装，供标准回测循环直接调用。
        在已有运行中的 asyncio 事件循环环境 (如 Jupyter Notebook / FastAPI / 异步测试) 中自动委派给专用线程，
        彻底杜绝 'RuntimeError: This event loop is already running' 冲突。
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        coro = self.get_kline_async(
            symbol=symbol,
            period=period,
            start=start,
            end=end,
            adjust=adjust,
            indicators=indicators,
            limit=limit
        )

        if loop is not None and loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                return executor.submit(lambda: asyncio.run(coro)).result()
        else:
            if loop is None:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            return loop.run_until_complete(coro)

    async def get_snapshots_async(self, symbols: List[str]) -> SnapshotBatchResponse:
        """异步批量获取股票实时行情快照"""
        from adapters.snapshot import snapshot_adapter
        snapshots, missing = await snapshot_adapter.fetch_snapshots(symbols)
        return SnapshotBatchResponse(
            count=len(snapshots),
            data=snapshots,
            missing=missing
        )

    def get_snapshots(self, symbols: List[str]) -> SnapshotBatchResponse:
        """
        同步批量获取股票实时行情快照 (兼容 Jupyter Notebook 与普通量化回测环境)。
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        coro = self.get_snapshots_async(symbols)

        if loop is not None and loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                return executor.submit(lambda: asyncio.run(coro)).result()
        else:
            if loop is None:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            return loop.run_until_complete(coro)

sdk = StockDataSDK()
