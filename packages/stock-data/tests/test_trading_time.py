import pytest
import datetime
from core.models import Market
from core.time import (
    market_timezone,
    timestamp_to_trading_date,
    date_to_utc_boundary,
    date_range_to_utc_boundary
)

def test_ashare_trading_date_conversion():
    """Test B: A-share UTC timestamp -> correct Shanghai trading_date"""
    # 2024-01-02 09:30:00 CST (北京时间开盘) 对应 2024-01-02 01:30:00 UTC
    dt_cst = datetime.datetime(2024, 1, 2, 9, 30, 0, tzinfo=market_timezone(Market.SH))
    ts_ms = int(dt_cst.astimezone(datetime.timezone.utc).timestamp() * 1000)

    trading_date = timestamp_to_trading_date(ts_ms, Market.SH)
    assert trading_date == "2024-01-02"

    # 测试 A 股收盘 15:00:00 CST
    dt_close = datetime.datetime(2024, 1, 2, 15, 0, 0, tzinfo=market_timezone(Market.SH))
    ts_close_ms = int(dt_close.astimezone(datetime.timezone.utc).timestamp() * 1000)
    assert timestamp_to_trading_date(ts_close_ms, Market.SH) == "2024-01-02"

    # 验证边界: 2024-01-02 对应的 UTC 毫秒起止区间
    start_ts, end_ts = date_range_to_utc_boundary("2024-01-02", "2024-01-02", Market.SH)
    assert start_ts <= ts_ms <= end_ts
    assert start_ts <= ts_close_ms <= end_ts

def test_hk_trading_date_conversion():
    """Test C: HK UTC timestamp -> correct Hong Kong trading_date (即使 UTC 日期与本地交易日不同)"""
    # 港股在 yfinance 中的日K线通常标记在当地时间 00:00:00 HKT
    # 2024-01-02 00:00:00 HKT 对应的 UTC 时间为 2024-01-01 16:00:00 UTC (自然日为前一天 01-01)
    dt_hk_midnight = datetime.datetime(2024, 1, 2, 0, 0, 0, tzinfo=market_timezone(Market.HK))
    ts_hk_midnight = int(dt_hk_midnight.astimezone(datetime.timezone.utc).timestamp() * 1000)

    # 核心验证：通过 timestamp_to_trading_date 必须准确映射回香港本地交易日 2024-01-02，绝不能误判为 2024-01-01
    trading_date = timestamp_to_trading_date(ts_hk_midnight, Market.HK)
    assert trading_date == "2024-01-02"

    # 港股下午收盘 16:00:00 HKT
    dt_hk_close = datetime.datetime(2024, 1, 2, 16, 0, 0, tzinfo=market_timezone(Market.HK))
    ts_hk_close = int(dt_hk_close.astimezone(datetime.timezone.utc).timestamp() * 1000)
    assert timestamp_to_trading_date(ts_hk_close, Market.HK) == "2024-01-02"

    # 验证区间包含
    start_ts, end_ts = date_range_to_utc_boundary("2024-01-02", "2024-01-02", Market.HK)
    assert start_ts <= ts_hk_midnight <= end_ts
    assert start_ts <= ts_hk_close <= end_ts

def test_us_dst_transition_trading_date():
    """Test D: US DST transition -> correct New York trading_date across winter EST and summer EDT"""
    # 1. 冬令时 (EST, UTC-5): 2024-01-02 16:00:00 EST -> 21:00:00 UTC
    dt_est = datetime.datetime(2024, 1, 2, 16, 0, 0, tzinfo=market_timezone(Market.US))
    ts_est = int(dt_est.astimezone(datetime.timezone.utc).timestamp() * 1000)
    assert timestamp_to_trading_date(ts_est, Market.US) == "2024-01-02"

    # 冬令时美股盘后 (19:30 EST) 对应的 UTC 时间已是次日 2024-01-03 00:30:00 UTC
    dt_est_post = datetime.datetime(2024, 1, 2, 19, 30, 0, tzinfo=market_timezone(Market.US))
    ts_est_post = int(dt_est_post.astimezone(datetime.timezone.utc).timestamp() * 1000)
    # 验证交易日依然正确归属于 New York 当地交易日 2024-01-02
    assert timestamp_to_trading_date(ts_est_post, Market.US) == "2024-01-02"

    # 2. 夏令时 (EDT, UTC-4): 2024-07-02 16:00:00 EDT -> 20:00:00 UTC
    dt_edt = datetime.datetime(2024, 7, 2, 16, 0, 0, tzinfo=market_timezone(Market.US))
    ts_edt = int(dt_edt.astimezone(datetime.timezone.utc).timestamp() * 1000)
    assert timestamp_to_trading_date(ts_edt, Market.US) == "2024-07-02"

    # 夏令时美股盘后 (20:30 EDT) 对应的 UTC 时间也是次日 2024-07-03 00:30:00 UTC
    dt_edt_post = datetime.datetime(2024, 7, 2, 20, 30, 0, tzinfo=market_timezone(Market.US))
    ts_edt_post = int(dt_edt_post.astimezone(datetime.timezone.utc).timestamp() * 1000)
    assert timestamp_to_trading_date(ts_edt_post, Market.US) == "2024-07-02"

    # 验证夏令时区间的 UTC 边界自动缩小为 UTC-4
    s_ts, e_ts = date_range_to_utc_boundary("2024-07-02", "2024-07-02", Market.US)
    assert s_ts <= ts_edt <= e_ts
    assert s_ts <= ts_edt_post <= e_ts

def test_utc_and_unsupported_market_timezone():
    """测试显式 UTC 市场与不支持/未知市场的时区解析 (严禁静默 fallback 到 Shanghai)"""
    # 1. 明确定义为 UTC 的市场类型
    assert market_timezone(Market.BINANCE).key == "UTC"
    assert market_timezone(Market.FX).key == "UTC"
    assert market_timezone("CRYPTO").key == "UTC"
    assert market_timezone("UTC").key == "UTC"

    # 2. 真正未知/不支持的 market 必须明确抛出 ValueError
    with pytest.raises(ValueError, match="Unsupported or unknown market"):
        market_timezone("UNKNOWN_EXCHANGE")

    with pytest.raises(ValueError, match="Unsupported or unknown market"):
        market_timezone("XYZ")
