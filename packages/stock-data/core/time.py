import datetime
import zoneinfo
from typing import Union, Tuple
from core.models import Market

def market_timezone(market: Union[Market, str]) -> zoneinfo.ZoneInfo:
    """
    获取交易所所在的本地标准时区对象 (zoneinfo.ZoneInfo)。
    自动处理夏令时 (DST, 如美东 EDT/EST) 与冬令时转换。
    """
    m = market.value if isinstance(market, Market) else str(market).upper()
    if m in ("SH", "SZ", "BJ"):
        return zoneinfo.ZoneInfo("Asia/Shanghai")
    elif m == "HK":
        return zoneinfo.ZoneInfo("Asia/Hong_Kong")
    elif m == "US":
        return zoneinfo.ZoneInfo("America/New_York")
    elif m in ("BINANCE", "CRYPTO", "FX", "UTC"):
        return zoneinfo.ZoneInfo("UTC")
    else:
        raise ValueError(f"Unsupported or unknown market for timezone mapping: {market}")

def timestamp_to_trading_date(ts_ms: int, market: Union[Market, str]) -> str:
    """
    将全局统一存储的 UTC 毫秒时间戳 (UTC instant) 转换为交易所本地交易日期 (YYYY-MM-DD)。
    杜绝将 UTC 日期直接当做当地交易日的离散偏差。
    """
    tz = market_timezone(market)
    dt = datetime.datetime.fromtimestamp(ts_ms / 1000, tz=tz)
    return dt.strftime("%Y-%m-%d")

def date_to_utc_boundary(date_str: str, market: Union[Market, str]) -> Tuple[int, int]:
    """
    获取交易所本地某个自然交易日对应的 UTC 毫秒时间戳闭区间 [start_ts, end_ts]。
    - start_ts: 当天本地 00:00:00.000 对应的 UTC 毫秒
    - end_ts: 当天本地 23:59:59.999 对应的 UTC 毫秒
    """
    tz = market_timezone(market)
    d = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
    dt_start = datetime.datetime.combine(d, datetime.time.min, tzinfo=tz)
    dt_end = datetime.datetime.combine(d, datetime.time.max, tzinfo=tz)
    start_ts = int(dt_start.astimezone(datetime.timezone.utc).timestamp() * 1000)
    end_ts = int(dt_end.astimezone(datetime.timezone.utc).timestamp() * 1000)
    return start_ts, end_ts

def date_range_to_utc_boundary(start_date: str, end_date: str, market: Union[Market, str]) -> Tuple[int, int]:
    """
    获取交易所本地日期区间 [start_date, end_date] 对应的完整 UTC 毫秒时间戳起止闭区间。
    """
    start_ts, _ = date_to_utc_boundary(start_date, market)
    _, end_ts = date_to_utc_boundary(end_date, market)
    return start_ts, end_ts
