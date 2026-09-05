from typing import Optional
import datetime
from fastapi import APIRouter, Query, HTTPException
from core.models import KlinePeriod, AdjustType, parse_symbol, format_symbol, SymbolInfo, Market, AssetType, KlineResponse, KlinePoint
from core.database import meta_db
from core.lock import single_flight
from storage.parquet_manager import parquet_mgr
from storage.compute import compute_engine

router = APIRouter(prefix="/api/v1/kline", tags=["Kline"])

@router.get("", response_model=KlineResponse)
async def get_kline(
    symbol: str = Query(..., description="标的代码，如 600519.SH.STK, AAPL.US.STK, 000300.SH.IDX, 510300.SH.ETF"),
    period: KlinePeriod = Query(KlinePeriod.D1, description="K线周期: 1m, 5m, 15m, 30m, 60m, 1d"),
    start: Optional[str] = Query(None, description="开始日期: YYYY-MM-DD (默认最近1年)"),
    end: Optional[str] = Query(None, description="结束日期: YYYY-MM-DD (默认当天)"),
    adjust: AdjustType = Query(AdjustType.RAW, description="复权类型: raw(不复权), qfq(前复权), hfq(后复权)"),
    indicators: Optional[str] = Query(None, description="可选计算量化技术指标，多个用逗号分隔，如: MA,MACD,RSI,BOLL,ATR,ALL"),
    limit: Optional[int] = Query(None, ge=1, le=50000, description="返回的最大K线柱数限制 (如 100)")
):
    ticker, market_str, type_str = parse_symbol(symbol)
    try:
        m = Market(market_str)
        t = AssetType(type_str)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid market or asset type in symbol: {symbol}")

    clean_symbol = format_symbol(ticker, market_str, type_str)

    # 1. 查找或补充元数据
    sym_record = meta_db.get_symbol(clean_symbol)
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
        # 宽基与核心默认标记
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
        meta_db.upsert_symbol(info)

    # 2. 补齐并严格校验时间区间
    today_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    if not end:
        end = today_str
    if not start:
        # 日K默认前1年，分钟K默认前5天
        days = 365 if period == KlinePeriod.D1 else 5
        start_dt = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)
        start = start_dt.strftime("%Y-%m-%d")

    # 边界防呆与资源保护校验
    if start > end:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid date range: start date ({start}) cannot be later than end date ({end})."
        )

    try:
        dt_s = datetime.datetime.strptime(start, "%Y-%m-%d")
        dt_e = datetime.datetime.strptime(end, "%Y-%m-%d")
        span_days = (dt_e - dt_s).days
        is_minute = period in [KlinePeriod.M1, KlinePeriod.M5, KlinePeriod.M15, KlinePeriod.M30, KlinePeriod.M60]
        if is_minute and span_days > 90:
            raise HTTPException(
                status_code=400,
                detail=f"Minute-level data request range ({span_days} days) exceeds maximum safe limit of 90 days. Please narrow the requested date range."
            )
        if not is_minute and span_days > 365 * 30:
            raise HTTPException(
                status_code=400,
                detail=f"Historical daily/weekly/monthly/yearly data request range ({span_days} days) exceeds maximum safe limit of 30 years."
            )
    except ValueError as e:
        if "time data" in str(e):
            raise HTTPException(status_code=400, detail=f"Invalid date format: {str(e)}. Expected YYYY-MM-DD.")
        raise

    # 3. 防并发击穿 SingleFlight 加锁按需加载 (LazyLoad + Smart Append)
    async with single_flight.acquire(clean_symbol):
        # 确定底层物理拉取与缓存的周期：
        # - 分钟系列 (1m, 5m, 15m, 30m, 60m) 底层统一以 1m 为基底；
        # - 日/周/月/年系列 (1d, 1w, 1M, 1Y) 底层统一以 1d 为基底。
        if period in [KlinePeriod.M5, KlinePeriod.M15, KlinePeriod.M30, KlinePeriod.M60]:
            fetch_period = KlinePeriod.M1
        elif period in [KlinePeriod.W1, KlinePeriod.MON1, KlinePeriod.Y1]:
            fetch_period = KlinePeriod.D1
        else:
            fetch_period = period

        df = await parquet_mgr.get_or_fetch(info, fetch_period, start, end)

    if df is None or df.is_empty():
        raise HTTPException(status_code=404, detail=f"No data found for {clean_symbol} in range [{start}, {end}]")

    # 4. 若请求衍生周期动态聚合合成
    if period in [KlinePeriod.M5, KlinePeriod.M15, KlinePeriod.M30, KlinePeriod.M60]:
        df = compute_engine.resample_minutes(df, period)
    elif period in [KlinePeriod.W1, KlinePeriod.MON1, KlinePeriod.Y1]:
        df = compute_engine.resample_higher_period(df, period)

    # 5. 动态复权处理
    if adjust != AdjustType.RAW:
        try:
            df = compute_engine.apply_adjustment(df, adjust)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    # 6. 若为 ETF 且有 NAV 数据，动态追加折溢价率；历史 K 线 adapter 目前不写入 NAV，跳过
    if t == AssetType.ETF and df is not None and "nav" in df.columns and df["nav"].drop_nulls().len() > 0:
        df = compute_engine.calculate_etf_premium(df)

    # 7. 若请求常用量化技术指标，执行向量化计算追加
    if indicators:
        ind_list = [x.strip() for x in indicators.split(",") if x.strip()]
        df = compute_engine.compute_indicators(df, ind_list)

    # 8. 数量上限截断处理
    if limit is not None and len(df) > limit:
        df = df.tail(limit)

    # 9. 序列化输出
    data_points = []
    for row in df.iter_rows(named=True):
        data_points.append(KlinePoint(
            timestamp=row["timestamp"],
            open=round(row["open"], 4),
            high=round(row["high"], 4),
            low=round(row["low"], 4),
            close=round(row["close"], 4),
            volume=row["volume"],
            amount=row.get("amount", 0.0),
            factor=row.get("factor"),
            nav=row.get("nav"),
            ma5=round(row["ma5"], 4) if "ma5" in row and row["ma5"] is not None else None,
            ma10=round(row["ma10"], 4) if "ma10" in row and row["ma10"] is not None else None,
            ma20=round(row["ma20"], 4) if "ma20" in row and row["ma20"] is not None else None,
            ma60=round(row["ma60"], 4) if "ma60" in row and row["ma60"] is not None else None,
            macd_dif=round(row["macd_dif"], 4) if "macd_dif" in row and row["macd_dif"] is not None else None,
            macd_dea=round(row["macd_dea"], 4) if "macd_dea" in row and row["macd_dea"] is not None else None,
            macd_hist=round(row["macd_hist"], 4) if "macd_hist" in row and row["macd_hist"] is not None else None,
            rsi=round(row["rsi"], 2) if "rsi" in row and row["rsi"] is not None else None,
            boll_upper=round(row["boll_upper"], 4) if "boll_upper" in row and row["boll_upper"] is not None else None,
            boll_mid=round(row["boll_mid"], 4) if "boll_mid" in row and row["boll_mid"] is not None else None,
            boll_lower=round(row["boll_lower"], 4) if "boll_lower" in row and row["boll_lower"] is not None else None,
            atr=round(row["atr"], 4) if "atr" in row and row["atr"] is not None else None,
        ))

    latest_point = data_points[-1] if data_points else None
    return KlineResponse(
        symbol=clean_symbol,
        period=period.value,
        adjust=adjust.value,
        count=len(data_points),
        latest=latest_point,
        data=data_points
    )
