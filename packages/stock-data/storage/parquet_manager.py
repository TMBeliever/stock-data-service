from pathlib import Path
from typing import Optional, Tuple, Dict, Any, List
import datetime
import os
import polars as pl
from config import settings
from core.models import SymbolInfo, KlinePeriod, AssetType, Market
from core.database import meta_db
from core.lock import single_flight
from core.time import timestamp_to_trading_date, date_range_to_utc_boundary, market_timezone
from storage.lock import storage_locks
from adapters.factory import adapter_factory

class ParquetManager:
    """
    负责时序 Parquet 的文件布局、读取、写入与 Smart Append (增量追加去重)
    """

    def get_file_path(self, info: SymbolInfo, period: str) -> Path:
        """获取标准化的 Parquet 存储路径"""
        market_str = info.market.value
        ticker_str = info.ticker
        type_str = info.asset_type.value
        clean_name = f"{ticker_str}_{type_str}"

        if info.is_benchmark:
            # 核心基准目录
            base_dir = settings.BENCHMARK_DIR / market_str
        else:
            # Lazy 缓存池目录
            sub_dir = "daily" if period in ["1d", "1w", "1M"] else "minute"
            base_dir = settings.CACHE_KLINE_DIR / sub_dir / market_str

        base_dir.mkdir(parents=True, exist_ok=True)
        file_name = f"{clean_name}.parquet" if period in ["1d", "1w", "1M"] else f"{clean_name}_{period}.parquet"
        return base_dir / file_name

    def read_parquet(self, path: Path) -> Optional[pl.DataFrame]:
        if not path.exists():
            return None
        try:
            return pl.read_parquet(path)
        except Exception as e:
            print(f"[ParquetManager] Error reading {path}: {e}")
            return None

    def write_parquet(self, path: Path, df: pl.DataFrame):
        """采用临时文件 + 原子重命名 (Atomic Replace) + 文件锁安全写入，防止断电写坏文件"""
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_name(f"{path.stem}_{datetime.datetime.now().strftime('%Y%m%d%H%M%S%f')}.tmp")
        with storage_locks.lock(str(path)):
            try:
                df.write_parquet(tmp_path, compression="zstd")
                os.replace(tmp_path, path)
            except Exception:
                if tmp_path.exists():
                    try:
                        tmp_path.unlink()
                    except Exception:
                        pass
                raise

    def _ts_to_date_str(self, ts_ms: int, market: Optional[Market] = None) -> str:
        return timestamp_to_trading_date(ts_ms, market or Market.SH)

    def _date_str_to_utc_ms(self, date_str: str, market: Optional[Market] = None) -> int:
        start_ts, _ = date_range_to_utc_boundary(date_str, date_str, market or Market.SH)
        return start_ts

    def _get_trading_dates_in_df(self, df: pl.DataFrame, market: Market) -> set[str]:
        """提取 DataFrame 中所有已存在的本地交易日 (YYYY-MM-DD)"""
        if df.is_empty() or "timestamp" not in df.columns:
            return set()
        try:
            tz = market_timezone(market)
            tz_key = tz.key
            dates = (
                df.select(
                    pl.col("timestamp")
                    .cast(pl.Datetime("ms", "UTC"))
                    .dt.convert_time_zone(tz_key)
                    .dt.strftime("%Y-%m-%d")
                    .unique()
                )["timestamp"]
            ).to_list()
            return set(dates)
        except Exception:
            return {timestamp_to_trading_date(int(ts), market) for ts in df["timestamp"]}

    def _detect_internal_gaps(
        self, df: pl.DataFrame, start_date: str, end_date: str, market: Market,
        symbol: Optional[str] = None, period: str = "1d"
    ) -> List[Tuple[str, str]]:
        """
        在指定日期闭区间 [start_date, end_date] 内检测内部缺失的真实交易日，
        并聚合成连续的缺失时间段 [(gap_start, gap_end), ...]
        - 自动排除周末 (周六、周日)
        - 自动排除数据库已登记的休市日 (is_trading_day is False)
        - 自动排除该标的已确认为无数据的非重复项 (is_symbol_no_data)
        """
        existing_dates = self._get_trading_dates_in_df(df, market)
        cur_dt = datetime.datetime.strptime(start_date, "%Y-%m-%d").date()
        end_dt = datetime.datetime.strptime(end_date, "%Y-%m-%d").date()

        missing_dates: List[str] = []
        market_str = market.value if isinstance(market, Market) else str(market)

        while cur_dt <= end_dt:
            d_str = cur_dt.strftime("%Y-%m-%d")
            # 若已有数据，不是 gap
            if d_str not in existing_dates:
                # 检查是否明确为休市日 (周末或已记录休市)
                is_open = meta_db.is_trading_day(market_str, d_str)
                if is_open is not False:
                    # 标的级空数据检查：若已知该标的在该日期无数据 (停牌/无交易)，则不触发重复拉取
                    if symbol and meta_db.is_symbol_no_data(symbol, period, d_str):
                        pass
                    else:
                        missing_dates.append(d_str)
            cur_dt += datetime.timedelta(days=1)

        if not missing_dates:
            return []

        # 将连续缺失日期聚合成区间 [(start, end), ...]
        gaps: List[Tuple[str, str]] = []
        gap_start = missing_dates[0]
        prev_date = datetime.datetime.strptime(gap_start, "%Y-%m-%d").date()

        for d_str in missing_dates[1:]:
            d_obj = datetime.datetime.strptime(d_str, "%Y-%m-%d").date()
            if (d_obj - prev_date).days == 1:
                prev_date = d_obj
            else:
                gaps.append((gap_start, prev_date.strftime("%Y-%m-%d")))
                gap_start = d_str
                prev_date = d_obj
        gaps.append((gap_start, prev_date.strftime("%Y-%m-%d")))

        return gaps

    async def get_or_fetch(self, info: SymbolInfo, period: KlinePeriod, start_date: str, end_date: str) -> Optional[pl.DataFrame]:
        """通过 SingleFlight 请求合并器调用内部加载，彻底消除同区间并发重复拉取"""
        flight_key = f"{info.symbol}:{period.value}:{start_date}:{end_date}"
        return await single_flight.do(flight_key, lambda: self._get_or_fetch_internal(info, period, start_date, end_date))

    async def _get_or_fetch_internal(self, info: SymbolInfo, period: KlinePeriod, start_date: str, end_date: str) -> Optional[pl.DataFrame]:
        """
        核心智能加载方法 (LazyLoad + Smart Append + Internal Gap Detection)：
        1. 检查本地是否有 Parquet 文件；
        2. 检查是否有左侧、右侧或内部缺失区间，只增量拉取缺失部分；
        3. 多区间去重合并与原子写入；
        4. 记录并更新 LRU 访问日志；
        5. 返回精确过滤后的时序数据。
        """
        period_str = period.value
        path = self.get_file_path(info, period_str)
        adapter = adapter_factory.get_adapter(info.market)

        cache_record = meta_db.get_cache_info(info.symbol, period_str)

        # 1. 检查本地缓存是否存在
        if path.exists():
            start_ts, end_ts = date_range_to_utc_boundary(start_date, end_date, info.market)

            # 优先根据 SQLite 覆盖元数据执行 scan_parquet 谓词下推 (真 LazyLoad，避免全表载入内存)
            if cache_record and cache_record.get("covered_start_date") and cache_record.get("covered_end_date"):
                if start_date >= cache_record["covered_start_date"] and end_date <= cache_record["covered_end_date"]:
                    try:
                        lazy_filtered = (
                            pl.scan_parquet(path)
                            .filter((pl.col("timestamp") >= start_ts) & (pl.col("timestamp") <= end_ts))
                            .collect()
                        )
                        if not lazy_filtered.is_empty():
                            # 确认 lazy_filtered 内部无缺口，若无内部历史缺口直接快速返回
                            internal_gaps = self._detect_internal_gaps(
                                lazy_filtered, start_date, end_date, info.market,
                                symbol=info.symbol, period=period_str
                            )
                            if not internal_gaps:
                                meta_db.touch_cache(info.symbol, period_str)
                                return lazy_filtered
                    except Exception as e:
                        print(f"[ParquetManager] scan_parquet error for {info.symbol}: {e}")

            existing_df = self.read_parquet(path)
            if existing_df is not None and not existing_df.is_empty():
                min_ts = int(existing_df["timestamp"].min())
                max_ts = int(existing_df["timestamp"].max())
                actual_covered_start = timestamp_to_trading_date(min_ts, info.market)
                actual_covered_end = timestamp_to_trading_date(max_ts, info.market)

                new_dfs = [existing_df]

                # 1. 若请求区间左侧超出已有数据，增量拉取左侧缺失区间
                if start_date < actual_covered_start:
                    earlier_df = adapter.fetch_daily(info, start_date, actual_covered_start) if period == KlinePeriod.D1 else adapter.fetch_minute(info, period, start_date, actual_covered_start)
                    if earlier_df is not None and not earlier_df.is_empty():
                        new_dfs.append(earlier_df)
                        for d_open in self._get_trading_dates_in_df(earlier_df, info.market):
                            meta_db.set_calendar_date(info.market.value, d_open, is_open=True)
                            meta_db.remove_symbol_no_data(info.symbol, period_str, d_open)

                # 2. 若请求区间右侧超出已有数据，增量拉取右侧缺失区间
                if end_date > actual_covered_end:
                    later_df = adapter.fetch_daily(info, actual_covered_end, end_date) if period == KlinePeriod.D1 else adapter.fetch_minute(info, period, actual_covered_end, end_date)
                    if later_df is not None and not later_df.is_empty():
                        new_dfs.append(later_df)
                        for d_open in self._get_trading_dates_in_df(later_df, info.market):
                            meta_db.set_calendar_date(info.market.value, d_open, is_open=True)
                            meta_db.remove_symbol_no_data(info.symbol, period_str, d_open)

                # 3. 检查并拉取已有数据区间内部的历史缺口 (Internal Gaps)
                eff_start = max(start_date, actual_covered_start)
                eff_end = min(end_date, actual_covered_end)
                if eff_start <= eff_end:
                    internal_gaps = self._detect_internal_gaps(
                        existing_df, eff_start, eff_end, info.market,
                        symbol=info.symbol, period=period_str
                    )
                    for gap_s, gap_e in internal_gaps:
                        gap_df = adapter.fetch_daily(info, gap_s, gap_e) if period == KlinePeriod.D1 else adapter.fetch_minute(info, period, gap_s, gap_e)
                        if gap_df is not None and not gap_df.is_empty():
                            new_dfs.append(gap_df)
                            # 登记实际有成交的日期为 OPEN (生命周期 UNKNOWN -> OPEN) 并清理旧 no-data 记录
                            for d_open in self._get_trading_dates_in_df(gap_df, info.market):
                                meta_db.set_calendar_date(info.market.value, d_open, is_open=True)
                                meta_db.remove_symbol_no_data(info.symbol, period_str, d_open)
                        else:
                            # 记录标的级无数据记录，杜绝无限重复拉取
                            # 严禁将全市场日历标记为 CLOSED (Provider Empty ≠ Market Closed)
                            # 自动排除已知休市日 (周末或已登记法定假日)
                            cur_d = datetime.datetime.strptime(gap_s, "%Y-%m-%d").date()
                            end_d = datetime.datetime.strptime(gap_e, "%Y-%m-%d").date()
                            while cur_d <= end_d:
                                d_str = cur_d.strftime("%Y-%m-%d")
                                if meta_db.is_trading_day(info.market.value, d_str) is not False:
                                    meta_db.mark_symbol_no_data(info.symbol, period_str, d_str)
                                cur_d += datetime.timedelta(days=1)

                # 若有任何新区间被增量拉取，合并、去重并原子写入
                if len(new_dfs) > 1:
                    merged_df = pl.concat(new_dfs).unique(subset=["timestamp"]).sort("timestamp")
                    if period == KlinePeriod.D1:
                        tz_key = market_timezone(info.market).key
                        merged_df = (
                            merged_df.with_columns(
                                pl.col("timestamp")
                                .cast(pl.Datetime("ms", "UTC"))
                                .dt.convert_time_zone(tz_key)
                                .dt.strftime("%Y-%m-%d")
                                .alias("_trading_date")
                            )
                            .unique(subset=["_trading_date"], keep="last")
                            .drop("_trading_date")
                            .sort("timestamp")
                        )
                    self.write_parquet(path, merged_df)
                    updated_df = merged_df
                else:
                    updated_df = existing_df

                new_min_ts = int(updated_df["timestamp"].min())
                new_max_ts = int(updated_df["timestamp"].max())
                file_size = path.stat().st_size
                meta_db.record_cache_access(
                    symbol=info.symbol,
                    period=period_str,
                    file_path=str(path),
                    file_size_bytes=file_size,
                    covered_start_date=timestamp_to_trading_date(new_min_ts, info.market),
                    covered_end_date=timestamp_to_trading_date(new_max_ts, info.market),
                    min_ts=new_min_ts,
                    max_ts=new_max_ts,
                    row_count=len(updated_df)
                )

                res_df = updated_df.filter((pl.col("timestamp") >= start_ts) & (pl.col("timestamp") <= end_ts))
                return res_df if not res_df.is_empty() else None

        # 2. 本地无缓存文件 -> 首次全量拉取
        if period == KlinePeriod.D1:
            fetched_df = adapter.fetch_daily(info, start_date, end_date)
        else:
            fetched_df = adapter.fetch_minute(info, period, start_date, end_date)

        if fetched_df is None or fetched_df.is_empty():
            # 记录标的级空数据，但不污染市场日历，且排除已知休市日
            cur_d = datetime.datetime.strptime(start_date, "%Y-%m-%d").date()
            end_d = datetime.datetime.strptime(end_date, "%Y-%m-%d").date()
            while cur_d <= end_d:
                d_str = cur_d.strftime("%Y-%m-%d")
                if meta_db.is_trading_day(info.market.value, d_str) is not False:
                    meta_db.mark_symbol_no_data(info.symbol, period_str, d_str)
                cur_d += datetime.timedelta(days=1)
            return None

        # 登记实际有成交的日期为 OPEN (生命周期 UNKNOWN -> OPEN) 并清除 stale no-data
        for d_open in self._get_trading_dates_in_df(fetched_df, info.market):
            meta_db.set_calendar_date(info.market.value, d_open, is_open=True)
            meta_db.remove_symbol_no_data(info.symbol, period_str, d_open)

        self.write_parquet(path, fetched_df)

        min_ts = int(fetched_df["timestamp"].min())
        max_ts = int(fetched_df["timestamp"].max())
        file_size = path.stat().st_size
        meta_db.record_cache_access(
            symbol=info.symbol,
            period=period_str,
            file_path=str(path),
            file_size_bytes=file_size,
            covered_start_date=timestamp_to_trading_date(min_ts, info.market),
            covered_end_date=timestamp_to_trading_date(max_ts, info.market),
            min_ts=min_ts,
            max_ts=max_ts,
            row_count=len(fetched_df)
        )

        start_ts, end_ts = date_range_to_utc_boundary(start_date, end_date, info.market)
        filtered = fetched_df.filter((pl.col("timestamp") >= start_ts) & (pl.col("timestamp") <= end_ts))
        return filtered if not filtered.is_empty() else None

    def reconcile_storage_metadata(self) -> Dict[str, int]:
        """
        轻量级双向存储对齐修补 (Startup / CLI Reconcile)：
        1. 检查 SQLite 元数据：清理已丢失物理文件的孤儿元数据记录；
        2. 扫描磁盘 Parquet 文件：发现已有文件但缺失元数据时，自动读取并恢复记录；
        3. 发现元数据与实际 Parquet 覆盖范围/行数不一致时，自动修正；
        4. 发现损坏的 Parquet 文件时，清理对应元数据防止脏读；
        5. 安全清理超过 60 秒的陈旧孤儿临时文件 (*.tmp)。
        """
        import time
        cleaned_orphans = 0
        restored_records = 0
        repaired_inconsistencies = 0
        cleaned_tmps = 0

        cache_dir = settings.CACHE_KLINE_DIR

        # 1. 清理孤儿元数据
        with meta_db._get_conn() as conn:
            rows = conn.execute("SELECT symbol, period, file_path FROM cache_access_logs").fetchall()
            for r in rows:
                p = Path(r["file_path"])
                if not p.exists():
                    meta_db.remove_cache_record(r["symbol"], r["period"])
                    cleaned_orphans += 1

        # 2. 扫描磁盘 Parquet 文件补充/校验元数据
        if cache_dir.exists():
            for p in cache_dir.rglob("*.parquet"):
                stem = p.stem
                market_name = p.parent.name
                period = "1d" if "daily" in p.parts else "1m"
                if "_" in stem and market_name in [m.value for m in Market]:
                    ticker_part, type_part = stem.split("_", 1)
                    if "_" in type_part:
                        type_part, period_part = type_part.split("_", 1)
                        period = period_part
                    symbol = f"{ticker_part}.{market_name}.{type_part}"
                else:
                    symbol = stem

                df = self.read_parquet(p)
                if df is None:
                    # 损坏的文件，清理元数据
                    meta_db.remove_cache_record(symbol, period)
                    continue

                if df.is_empty() or "timestamp" not in df.columns:
                    continue

                min_ts = int(df["timestamp"].min())
                max_ts = int(df["timestamp"].max())
                file_size = p.stat().st_size
                market_obj = Market(market_name) if market_name in [m.value for m in Market] else Market.SH
                covered_start = timestamp_to_trading_date(min_ts, market_obj)
                covered_end = timestamp_to_trading_date(max_ts, market_obj)
                row_count = len(df)

                rec = meta_db.get_cache_info(symbol, period)
                if not rec:
                    meta_db.record_cache_access(
                        symbol=symbol,
                        period=period,
                        file_path=str(p),
                        file_size_bytes=file_size,
                        covered_start_date=covered_start,
                        covered_end_date=covered_end,
                        min_ts=min_ts,
                        max_ts=max_ts,
                        row_count=row_count
                    )
                    restored_records += 1
                else:
                    if (rec.get("row_count") != row_count or 
                        rec.get("covered_start_date") != covered_start or 
                        rec.get("covered_end_date") != covered_end):
                        meta_db.record_cache_access(
                            symbol=symbol,
                            period=period,
                            file_path=str(p),
                            file_size_bytes=file_size,
                            covered_start_date=covered_start,
                            covered_end_date=covered_end,
                            min_ts=min_ts,
                            max_ts=max_ts,
                            row_count=row_count
                        )
                        repaired_inconsistencies += 1

            # 3. 清理陈旧的孤儿临时文件 (*.tmp，超过 60 秒未变动)
            now = time.time()
            for tmp_p in cache_dir.rglob("*.tmp"):
                try:
                    if now - tmp_p.stat().st_mtime > 60:
                        tmp_p.unlink()
                        cleaned_tmps += 1
                except Exception:
                    pass

        # 4. 清理已超期的 stale symbol_no_data 记录
        cleaned_expired_no_data = meta_db.cleanup_expired_symbol_no_data()

        return {
            "cleaned_orphans": cleaned_orphans,
            "restored_records": restored_records,
            "repaired_inconsistencies": repaired_inconsistencies,
            "cleaned_tmps": cleaned_tmps,
            "cleaned_expired_no_data": cleaned_expired_no_data
        }

parquet_mgr = ParquetManager()
