import duckdb
import polars as pl
from core.models import AdjustType, KlinePeriod

class ComputeEngine:
    """
    基于 DuckDB 内存分析的极速计算引擎：
    - 动态复权算子 (前复权 QFQ / 后复权 HFQ / 不复权 RAW)
    - 动态周期重采样 (1m 动态合成 5m / 15m / 30m / 60m)
    - ETF 折溢价率动态推导
    """
    def __init__(self):
        # 不保留共享连接：duckdb :memory: 连接不支持并发访问，每次查询按需创建独立连接
        pass

    def _new_conn(self) -> duckdb.DuckDBPyConnection:
        return duckdb.connect(":memory:")

    def apply_adjustment(self, df: pl.DataFrame, adjust: AdjustType) -> pl.DataFrame:
        """
        动态复权计算:
        若 adjust == RAW: 直接返回原始价格
        若 adjust == QFQ (前复权): 价格 * (factor / latest_factor)
        若 adjust == HFQ (后复权): 价格 * factor
        """
        if adjust == AdjustType.RAW or "factor" not in df.columns or df.is_empty():
            return df

        if df["factor"].null_count() == len(df):
            raise ValueError(f"Cannot perform {adjust.value} adjustment: adjustment factor is unavailable for this asset.")

        if "symbol" in df.columns and df["symbol"].n_unique() > 1:
            # 存在多标的混合时序数据，严格按 symbol 分组填充，严禁跨标的因子污染
            filled_factor_col = pl.col("factor").forward_fill().backward_fill().over("symbol")
            latest_factor_col = pl.col("factor").forward_fill().backward_fill().last().over("symbol")
            if adjust == AdjustType.QFQ:
                ratio_expr = filled_factor_col / latest_factor_col
            elif adjust == AdjustType.HFQ:
                ratio_expr = filled_factor_col
            else:
                return df
        else:
            # 单标的标准时序数据
            valid_factors = df["factor"].drop_nulls()
            latest_factor = valid_factors[-1] if len(valid_factors) > 0 else 1.0

            # 若存在局部缺失 factor (如分钟线重采样或除权日过渡期间)，使用前向填充延续该资产除权区间的真实复权因子
            # 严禁静默替换为 1.0，严禁输出破坏指标计算的 NULL 价格
            filled_factor_col = pl.col("factor").forward_fill().backward_fill()

            if adjust == AdjustType.QFQ:
                ratio_expr = filled_factor_col / latest_factor
            elif adjust == AdjustType.HFQ:
                ratio_expr = filled_factor_col
            else:
                return df

        return df.with_columns([
            (pl.col("open") * ratio_expr).cast(pl.Float32).alias("open"),
            (pl.col("high") * ratio_expr).cast(pl.Float32).alias("high"),
            (pl.col("low") * ratio_expr).cast(pl.Float32).alias("low"),
            (pl.col("close") * ratio_expr).cast(pl.Float32).alias("close"),
        ])

    def _compute_session_bucket(self, ts_ms: int, interval_mins: int) -> int:
        import datetime
        dt_utc = datetime.datetime.fromtimestamp(ts_ms / 1000, tz=datetime.timezone.utc)
        dt_bj = dt_utc.astimezone(datetime.timezone(datetime.timedelta(hours=8)))
        hh = dt_bj.hour
        mm = dt_bj.minute

        interval_ms = interval_mins * 60 * 1000

        # A 股早盘 Session: 09:30 - 11:30
        if (hh == 9 and mm >= 30) or hh == 10 or (hh == 11 and mm <= 30):
            mins_from_start = min((hh - 9) * 60 + mm - 30, 119)
            bucket_idx = mins_from_start // interval_mins
            start_ts = int(dt_bj.replace(hour=9, minute=30, second=0, microsecond=0).timestamp() * 1000)
            return start_ts + bucket_idx * interval_ms

        # A 股午盘 Session: 13:00 - 15:00
        if hh in (13, 14) or (hh == 15 and mm == 0):
            mins_from_start = min((hh - 13) * 60 + mm, 119)
            bucket_idx = mins_from_start // interval_mins
            start_ts = int(dt_bj.replace(hour=13, minute=0, second=0, microsecond=0).timestamp() * 1000)
            return start_ts + bucket_idx * interval_ms

        # 默认/通用按自然间隔切桶
        return (ts_ms // interval_ms) * interval_ms

    def resample_minutes(self, df: pl.DataFrame, target_period: KlinePeriod) -> pl.DataFrame:
        """
        利用 DuckDB 进行分钟K线动态聚合合成 (如 1m -> 5m / 15m / 30m / 60m)，
        具备交易 Session 隔离感知，杜绝早盘 11:30 与午盘 13:00 跨休市合并。
        """
        if df.is_empty() or target_period == KlinePeriod.M1:
            return df

        minutes_map = {
            KlinePeriod.M5: 5,
            KlinePeriod.M15: 15,
            KlinePeriod.M30: 30,
            KlinePeriod.M60: 60,
        }
        mins = minutes_map.get(target_period)
        if not mins:
            return df

        # 计算感知交易 Session 的标准时桶时间戳
        bucket_ts = [self._compute_session_bucket(int(ts), mins) for ts in df["timestamp"]]
        df_bucketed = df.with_columns(pl.Series("bucket_ts", bucket_ts, dtype=pl.Int64))

        # DuckDB 内存聚合（每次创建独立连接，避免并发崩溃）
        arrow_table = df_bucketed.to_arrow()
        query = f"""
        SELECT
            bucket_ts AS timestamp,
            FIRST(open ORDER BY timestamp ASC) AS open,
            MAX(high) AS high,
            MIN(low) AS low,
            LAST(close ORDER BY timestamp ASC) AS close,
            SUM(volume) AS volume,
            SUM(amount) AS amount,
            LAST(factor ORDER BY timestamp ASC) FILTER (WHERE factor IS NOT NULL) AS factor,
            LAST(nav ORDER BY timestamp ASC) FILTER (WHERE nav IS NOT NULL) AS nav
        FROM arrow_table
        GROUP BY bucket_ts
        ORDER BY timestamp ASC;
        """
        res_arrow = self._new_conn().execute(query).arrow()
        return pl.from_arrow(res_arrow)

    def resample_higher_period(self, df: pl.DataFrame, target_period: KlinePeriod) -> pl.DataFrame:
        """
        利用 DuckDB 进行更高层级长周期 K 线的动态聚合合成 (如 1d -> 1w / 1M / 1Y)。
        - 1w (周K): 按自然周 (以周一为起始时桶) 聚合
        - 1M (月K): 按自然月度聚合
        - 1Y (年K): 按自然年度聚合
        聚合规则:
        - timestamp: 采用该周期首个真实交易日的毫秒时间戳 (符合量化主流规范)
        - open: 周期第一天开盘价 (FIRST)
        - high: 周期内最高价 (MAX)
        - low: 周期内最低价 (MIN)
        - close: 周期最后一天收盘价 (LAST)
        - volume/amount: 周期内总量/总额累加 (SUM)
        - factor/nav: 周期末最新有效复权因子与净值 (LAST non-null)
        """
        if df.is_empty() or target_period == KlinePeriod.D1:
            return df

        trunc_map = {
            KlinePeriod.W1: "week",
            KlinePeriod.MON1: "month",
            KlinePeriod.Y1: "year",
        }
        trunc_unit = trunc_map.get(target_period)
        if not trunc_unit:
            return df

        arrow_table = df.to_arrow()
        query = f"""
        SELECT
            FIRST(timestamp ORDER BY timestamp ASC) AS timestamp,
            FIRST(open ORDER BY timestamp ASC) AS open,
            MAX(high) AS high,
            MIN(low) AS low,
            LAST(close ORDER BY timestamp ASC) AS close,
            SUM(volume) AS volume,
            SUM(amount) AS amount,
            LAST(factor ORDER BY timestamp ASC) FILTER (WHERE factor IS NOT NULL) AS factor,
            LAST(nav ORDER BY timestamp ASC) FILTER (WHERE nav IS NOT NULL) AS nav
        FROM arrow_table
        GROUP BY date_trunc('{trunc_unit}', epoch_ms(timestamp))
        ORDER BY timestamp ASC;
        """
        res_arrow = self._new_conn().execute(query).arrow()
        return pl.from_arrow(res_arrow)

    def calculate_etf_premium(self, df: pl.DataFrame) -> pl.DataFrame:
        """计算 ETF 折溢价率: (close - nav) / nav * 100%"""
        if "nav" not in df.columns or df.is_empty():
            return df

        return df.with_columns(
            pl.when(pl.col("nav").is_not_null() & (pl.col("nav") > 0))
            .then(((pl.col("close") - pl.col("nav")) / pl.col("nav") * 100.0).cast(pl.Float32))
            .otherwise(None)
            .alias("premium_rate")
        )

    def compute_indicators(self, df: pl.DataFrame, indicators: list[str]) -> pl.DataFrame:
        """
        向量化计算常用量化技术指标:
        - 移动平均线: MA5, MA10, MA20, MA60
        - 趋势指标: MACD (macd_dif, macd_dea, macd_hist)
        - 摆动指标: RSI (14周期)
        - 通道指标: BOLL (boll_upper, boll_mid, boll_lower)
        - 波动率指标: ATR (14周期真实波幅)
        """
        if df.is_empty() or not indicators:
            return df

        inds = [i.strip().upper() for i in indicators]
        new_cols = []

        # 1. 均线计算
        for n in [5, 10, 20, 60]:
            if f"MA{n}" in inds or "MA" in inds or "ALL" in inds:
                new_cols.append(pl.col("close").rolling_mean(window_size=n).cast(pl.Float32).alias(f"ma{n}"))

        # 2. BOLL 布林带
        if "BOLL" in inds or "ALL" in inds:
            mid = pl.col("close").rolling_mean(window_size=20).cast(pl.Float32)
            std = pl.col("close").rolling_std(window_size=20).cast(pl.Float32)
            new_cols.append(mid.alias("boll_mid"))
            new_cols.append((mid + 2.0 * std).alias("boll_upper"))
            new_cols.append((mid - 2.0 * std).alias("boll_lower"))

        if new_cols:
            df = df.with_columns(new_cols)

        # 3. MACD 经典指标 (12, 26, 9)
        if "MACD" in inds or "ALL" in inds:
            ema12 = df["close"].ewm_mean(span=12)
            ema26 = df["close"].ewm_mean(span=26)
            dif = (ema12 - ema26).cast(pl.Float32)
            dea = dif.ewm_mean(span=9).cast(pl.Float32)
            hist = ((dif - dea) * 2.0).cast(pl.Float32)
            df = df.with_columns([
                dif.alias("macd_dif"),
                dea.alias("macd_dea"),
                hist.alias("macd_hist")
            ])

        # 4. RSI (14 周期)
        if "RSI" in inds or "ALL" in inds:
            close_diff = df["close"].diff()
            gain = pl.when(close_diff > 0).then(close_diff).otherwise(0.0)
            loss = pl.when(close_diff < 0).then(-close_diff).otherwise(0.0)
            avg_gain = gain.ewm_mean(span=14)
            avg_loss = loss.ewm_mean(span=14)
            rs = avg_gain / (avg_loss + 1e-9)
            rsi = (100.0 - (100.0 / (1.0 + rs))).cast(pl.Float32)
            df = df.with_columns(rsi.alias("rsi"))

        # 5. ATR (14 周期)
        if "ATR" in inds or "ALL" in inds:
            prev_close = df["close"].shift(1)
            tr1 = df["high"] - df["low"]
            tr2 = (df["high"] - prev_close).abs()
            tr3 = (df["low"] - prev_close).abs()
            # 真实波幅 TR = max(tr1, tr2, tr3)
            tr = pl.concat_list([tr1, tr2, tr3]).list.max()
            atr = tr.rolling_mean(window_size=14).cast(pl.Float32)
            df = df.with_columns(atr.alias("atr"))

        return df

compute_engine = ComputeEngine()
