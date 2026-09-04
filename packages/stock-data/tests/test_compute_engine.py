import pytest
import polars as pl
from storage.compute import ComputeEngine
from core.models import AdjustType, KlinePeriod

@pytest.fixture
def engine():
    return ComputeEngine()

def test_dynamic_adjustment_qfq_and_hfq(engine):
    # 模拟真实分红送股前后的价格与复权因子
    # Day 1: Close = 100.0, Factor = 1.0
    # Day 2: Close = 50.0 (10送10除权), Factor = 2.0
    df = pl.DataFrame({
        "timestamp": [1700000000000, 1700086400000],
        "open": [99.0, 49.0],
        "high": [101.0, 51.0],
        "low": [98.0, 48.0],
        "close": [100.0, 50.0],
        "volume": [1000.0, 2000.0],
        "amount": [100000.0, 100000.0],
        "factor": [1.0, 2.0],
        "nav": [None, None]
    })

    # 1. 不复权 RAW
    raw_res = engine.apply_adjustment(df, AdjustType.RAW)
    assert raw_res["close"][0] == 100.0
    assert raw_res["close"][1] == 50.0

    # 2. 前复权 QFQ: 最新日为基准，Day 1 前复权价格 = 100 * (1.0 / 2.0) = 50.0
    qfq_res = engine.apply_adjustment(df, AdjustType.QFQ)
    assert round(float(qfq_res["close"][0]), 2) == 50.0
    assert round(float(qfq_res["close"][1]), 2) == 50.0

    # 3. 后复权 HFQ: Day 1 = 100 * 1.0 = 100.0, Day 2 = 50 * 2.0 = 100.0
    hfq_res = engine.apply_adjustment(df, AdjustType.HFQ)
    assert round(float(hfq_res["close"][0]), 2) == 100.0
    assert round(float(hfq_res["close"][1]), 2) == 100.0

def test_missing_factor_disallows_silent_adjustment(engine):
    """验证当复权因子缺失/全为 None 时，禁止静默伪装成 1.0 复权，必须明确拒绝或抛出异常"""
    df_no_factor = pl.DataFrame({
        "timestamp": [1700000000000, 1700086400000],
        "open": [100.0, 50.0],
        "high": [101.0, 51.0],
        "low": [98.0, 48.0],
        "close": [100.0, 50.0],
        "volume": [1000.0, 2000.0],
        "amount": [100000.0, 100000.0],
        "factor": [None, None],
        "nav": [None, None]
    })

    # RAW 不受影响
    raw_res = engine.apply_adjustment(df_no_factor, AdjustType.RAW)
    assert raw_res["close"][0] == 100.0

    # QFQ / HFQ 必须显式报错，杜绝将未知因子伪造为 1.0
    with pytest.raises(ValueError, match="adjustment factor is unavailable"):
        engine.apply_adjustment(df_no_factor, AdjustType.QFQ)

    with pytest.raises(ValueError, match="adjustment factor is unavailable"):
        engine.apply_adjustment(df_no_factor, AdjustType.HFQ)

def test_partial_missing_factor_contract_prevents_null_prices(engine):
    """
    P1 审计：验证当出现局部 missing factor (如除权交接或中间采样缺失) 时：
    - 绝不允许输出含有 NULL 的 open/high/low/close 价格 (破坏指标和策略计算)
    - 采用前向与后向连续填充延续除权因子
    """
    df_partial = pl.DataFrame({
        "timestamp": [1700000000000, 1700086400000, 1700172800000],
        "open": [10.0, 11.0, 12.0],
        "high": [10.5, 11.5, 12.5],
        "low": [9.5, 10.5, 11.5],
        "close": [10.0, 11.0, 12.0],
        "volume": [100.0, 100.0, 100.0],
        "amount": [1000.0, 1100.0, 1200.0],
        "factor": [1.0, None, 2.0], # 中间条目缺失 factor
        "nav": [None, None, None]
    })

    qfq_df = engine.apply_adjustment(df_partial, AdjustType.QFQ)
    # 核心断言：价格绝对不能存在 NULL
    assert qfq_df["close"].null_count() == 0
    assert qfq_df["open"].null_count() == 0
    assert len(qfq_df) == 3

    hfq_df = engine.apply_adjustment(df_partial, AdjustType.HFQ)
    assert hfq_df["close"].null_count() == 0
    assert hfq_df["open"].null_count() == 0

def test_factor_adjustment_test_matrix(engine):
    """
    P1-2 & P1-6 审计：Factor Adjustment 严格数值矩阵与 OHLC 不变量测试
    覆盖：
    - Case 1: [1.0, None, 1.0] -> 连续常量
    - Case 2: [1.0, None, 2.0] -> 除权阶梯
    - Case 3: [None, 1.0, 1.0] -> 头部缺失填充
    - Case 4: [1.0, 1.0, None] -> 尾部缺失填充
    - Case 5: [None, None, None] -> 明确抛出 ValueError
    - Case 6: [1.0, 1.0, 1.2, 1.2] -> OHLC 不变量严格保持
    """
    # Case 1: [1.0, None, 1.0]
    df1 = pl.DataFrame({
        "timestamp": [1000, 2000, 3000],
        "open": [100.0, 100.0, 100.0], "high": [105.0, 105.0, 105.0],
        "low": [95.0, 95.0, 95.0], "close": [100.0, 100.0, 100.0],
        "volume": [10.0, 10.0, 10.0], "amount": [1000.0, 1000.0, 1000.0],
        "factor": [1.0, None, 1.0], "nav": [None, None, None]
    })
    qfq1 = engine.apply_adjustment(df1, AdjustType.QFQ)
    assert qfq1["close"].to_list() == [100.0, 100.0, 100.0]

    # Case 2: [1.0, None, 2.0] -> 中间项向前延续 1.0
    df2 = pl.DataFrame({
        "timestamp": [1000, 2000, 3000],
        "open": [100.0, 100.0, 50.0], "high": [105.0, 105.0, 55.0],
        "low": [95.0, 95.0, 45.0], "close": [100.0, 100.0, 50.0],
        "volume": [10.0, 10.0, 20.0], "amount": [1000.0, 1000.0, 1000.0],
        "factor": [1.0, None, 2.0], "nav": [None, None, None]
    })
    # QFQ: latest_factor = 2.0. 前两项 100 * (1.0/2.0) = 50.0, 第三项 50 * (2.0/2.0) = 50.0
    qfq2 = engine.apply_adjustment(df2, AdjustType.QFQ)
    assert [round(x, 2) for x in qfq2["close"].to_list()] == [50.0, 50.0, 50.0]

    # Case 3: [None, 1.0, 1.0] -> 头部向后补齐 1.0
    df3 = pl.DataFrame({
        "timestamp": [1000, 2000, 3000],
        "open": [10.0, 10.0, 10.0], "high": [12.0, 12.0, 12.0],
        "low": [8.0, 8.0, 8.0], "close": [10.0, 10.0, 10.0],
        "volume": [10.0, 10.0, 10.0], "amount": [100.0, 100.0, 100.0],
        "factor": [None, 1.0, 1.0], "nav": [None, None, None]
    })
    qfq3 = engine.apply_adjustment(df3, AdjustType.QFQ)
    assert qfq3["close"].to_list() == [10.0, 10.0, 10.0]

    # Case 4: [1.0, 1.0, None] -> 尾部向前补齐 1.0
    df4 = pl.DataFrame({
        "timestamp": [1000, 2000, 3000],
        "open": [10.0, 10.0, 10.0], "high": [12.0, 12.0, 12.0],
        "low": [8.0, 8.0, 8.0], "close": [10.0, 10.0, 10.0],
        "volume": [10.0, 10.0, 10.0], "amount": [100.0, 100.0, 100.0],
        "factor": [1.0, 1.0, None], "nav": [None, None, None]
    })
    qfq4 = engine.apply_adjustment(df4, AdjustType.QFQ)
    assert qfq4["close"].to_list() == [10.0, 10.0, 10.0]

    # Case 5: 全 NULL 必须明确失败，严禁伪造 1.0
    df5 = pl.DataFrame({
        "timestamp": [1000, 2000],
        "open": [10.0, 10.0], "high": [10.0, 10.0], "low": [10.0, 10.0], "close": [10.0, 10.0],
        "volume": [1.0, 1.0], "amount": [10.0, 10.0],
        "factor": [None, None], "nav": [None, None]
    })
    with pytest.raises(ValueError, match="adjustment factor is unavailable"):
        engine.apply_adjustment(df5, AdjustType.QFQ)

    # Case 6: OHLC 不变量检验 (high >= max(open, close, low), low <= min(open, close, high))
    df6 = pl.DataFrame({
        "timestamp": [1000, 2000, 3000, 4000],
        "open": [100.0, 102.0, 85.0, 86.0],
        "high": [105.0, 106.0, 88.0, 89.0],
        "low": [98.0, 99.0, 83.0, 84.0],
        "close": [101.0, 103.0, 87.0, 88.0],
        "volume": [100.0, 100.0, 120.0, 120.0],
        "amount": [10000.0, 10000.0, 10000.0, 10000.0],
        "factor": [1.0, 1.0, 1.2, 1.2],
        "nav": [None, None, None, None]
    })
    qfq6 = engine.apply_adjustment(df6, AdjustType.QFQ)
    for row in qfq6.to_dicts():
        assert row["high"] >= max(row["open"], row["close"], row["low"])
        assert row["low"] <= min(row["open"], row["close"], row["high"])

def test_multi_symbol_factor_isolation(engine):
    """
    P1-3 审计：多标的混合时序数据因子隔离测试
    验证 Symbol A 的因子绝对不能传递到 Symbol B
    """
    df_multi = pl.DataFrame({
        "timestamp": [1000, 2000, 1000, 2000],
        "symbol": ["A", "A", "B", "B"],
        "open": [10.0, 10.0, 100.0, 100.0],
        "high": [10.0, 10.0, 100.0, 100.0],
        "low": [10.0, 10.0, 100.0, 100.0],
        "close": [10.0, 10.0, 100.0, 100.0],
        "volume": [10.0, 10.0, 10.0, 10.0],
        "amount": [100.0, 100.0, 1000.0, 1000.0],
        "factor": [1.0, 2.0, 10.0, 20.0], # A 因子是 1->2, B 因子是 10->20
        "nav": [None, None, None, None]
    })

    qfq = engine.apply_adjustment(df_multi, AdjustType.QFQ)
    a_closes = qfq.filter(pl.col("symbol") == "A")["close"].to_list()
    b_closes = qfq.filter(pl.col("symbol") == "B")["close"].to_list()

    # A: 10 * (1.0/2.0) = 5.0, 10 * (2.0/2.0) = 10.0
    assert [round(x, 2) for x in a_closes] == [5.0, 10.0]
    # B: 100 * (10.0/20.0) = 50.0, 100 * (20.0/20.0) = 100.0
    assert [round(x, 2) for x in b_closes] == [50.0, 100.0]

def test_dynamic_resample_minutes(engine):
    # 构造连续 5 条 1 分钟线数据，对齐至 5 分钟整点 (1700000400000 % 300000 == 0)
    base_ts = 1700000400000
    timestamps = [base_ts + i * 60000 for i in range(5)]
    opens = [10.0, 10.2, 10.5, 10.1, 10.3]
    highs = [10.4, 10.6, 10.8, 10.3, 10.5]
    lows = [9.8, 10.0, 10.2, 9.9, 10.1]
    closes = [10.2, 10.5, 10.1, 10.3, 10.7]
    volumes = [100.0, 100.0, 100.0, 100.0, 100.0]

    df_1m = pl.DataFrame({
        "timestamp": timestamps,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
        "amount": [v * 10 for v in volumes],
        "factor": [1.0] * 5,
        "nav": [None] * 5
    })

    # 动态合成为 5m K线
    df_5m = engine.resample_minutes(df_1m, KlinePeriod.M5)
    assert len(df_5m) == 1
    row = df_5m.row(0, named=True)
    assert row["open"] == 10.0      # 第一根的 open
    assert row["high"] == 10.8      # 5 根中的最高 high
    assert row["low"] == 9.8        # 5 根中的最低 low
    assert row["close"] == 10.7     # 最后一根的 close
    assert row["volume"] == 500.0   # 成交量总和

def test_resample_preserves_last_non_null_factor_and_nav(engine):
    """
    P1/P2 测试：验证 resample 时若 bucket 尾部出现 NULL factor/nav，
    不能将整个 bucket 的 factor/nav 污染为 NULL，必须保留该 bucket 内最后一个有效的 non-null 值。
    """
    base_ts = 1700000400000
    timestamps = [base_ts + i * 60000 for i in range(5)]
    opens = [10.0, 10.2, 10.5, 10.1, 10.3]
    highs = [10.4, 10.6, 10.8, 10.3, 10.5]
    lows = [9.8, 10.0, 10.2, 9.9, 10.1]
    closes = [10.2, 10.5, 10.1, 10.3, 10.7]
    volumes = [100.0, 100.0, 100.0, 100.0, 100.0]

    # 前 3 根有有效 factor 1.25 和 nav 3.05，后 2 根为 NULL
    factors = [1.20, 1.25, 1.25, None, None]
    navs = [3.00, 3.05, 3.05, None, None]

    df_1m = pl.DataFrame({
        "timestamp": timestamps,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
        "amount": [v * 10 for v in volumes],
        "factor": factors,
        "nav": navs
    })

    df_5m = engine.resample_minutes(df_1m, KlinePeriod.M5)
    assert len(df_5m) == 1
    row = df_5m.row(0, named=True)
    assert row["factor"] == pytest.approx(1.25)
    assert row["nav"] == pytest.approx(3.05)

    # 验证全 NULL 的情况：若整个 bucket 都是 NULL，依然保持 NULL，不伪造 1.0
    df_all_null = df_1m.with_columns([
        pl.Series("factor", [None] * 5),
        pl.Series("nav", [None] * 5)
    ])
    df_5m_null = engine.resample_minutes(df_all_null, KlinePeriod.M5)
    row_null = df_5m_null.row(0, named=True)
    assert row_null["factor"] is None
    assert row_null["nav"] is None

def test_etf_premium_discount(engine):
    # ETF 收盘价 3.10，基金单位净值 3.00，折溢价率应为 +3.333%
    df_etf = pl.DataFrame({
        "timestamp": [1700000000000],
        "open": [3.05],
        "high": [3.15],
        "low": [3.00],
        "close": [3.10],
        "volume": [100000.0],
        "amount": [310000.0],
        "factor": [1.0],
        "nav": [3.00]
    })

    res = engine.calculate_etf_premium(df_etf)
    assert "premium_rate" in res.columns
    assert round(float(res["premium_rate"][0]), 2) == 3.33

def test_compute_indicators(engine):
    # 构造 30 根行情柱验证常用指标计算
    prices = [10.0 + i * 0.5 for i in range(30)]
    df = pl.DataFrame({
        "timestamp": [1700000000000 + i * 86400000 for i in range(30)],
        "open": prices,
        "high": [p + 0.2 for p in prices],
        "low": [p - 0.2 for p in prices],
        "close": prices,
        "volume": [1000.0] * 30,
        "amount": [10000.0] * 30
    })

    res = engine.compute_indicators(df, ["MA", "MACD", "RSI", "BOLL", "ATR"])
    assert "ma5" in res.columns
    assert "ma20" in res.columns
    assert "macd_dif" in res.columns
    assert "macd_dea" in res.columns
    assert "rsi" in res.columns
    assert "boll_mid" in res.columns
    assert "atr" in res.columns
    assert res["ma5"][-1] is not None
    assert res["macd_dif"][-1] is not None
    assert res["rsi"][-1] is not None

def test_ashare_session_aware_resample_no_lunch_merging(engine):
    """测试 A 股早盘 11:25 与午盘 13:05 在 60m 聚合时绝不跨休市错误合并为一个 bar"""
    import datetime
    dt_morning = datetime.datetime(2024, 5, 10, 11, 25, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=8)))
    dt_afternoon = datetime.datetime(2024, 5, 10, 13, 5, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=8)))

    ts_morning = int(dt_morning.astimezone(datetime.timezone.utc).timestamp() * 1000)
    ts_afternoon = int(dt_afternoon.astimezone(datetime.timezone.utc).timestamp() * 1000)

    df_cross_session = pl.DataFrame({
        "timestamp": [ts_morning, ts_afternoon],
        "open": [10.0, 20.0],
        "high": [10.5, 20.5],
        "low": [9.5, 19.5],
        "close": [10.2, 20.2],
        "volume": [100.0, 200.0],
        "amount": [1000.0, 2000.0],
        "factor": [1.0, 1.0],
        "nav": [None, None]
    })

    # 合成为 60m 周期
    df_60m = engine.resample_minutes(df_cross_session, KlinePeriod.M60)

    # 验证早盘与午盘分属两个独立 bar
    assert len(df_60m) == 2
    row1 = df_60m.row(0, named=True)
    row2 = df_60m.row(1, named=True)

    dt1 = datetime.datetime.fromtimestamp(row1["timestamp"] / 1000, tz=datetime.timezone(datetime.timedelta(hours=8)))
    assert dt1.hour == 10 and dt1.minute == 30
    assert row1["open"] == 10.0

    dt2 = datetime.datetime.fromtimestamp(row2["timestamp"] / 1000, tz=datetime.timezone(datetime.timedelta(hours=8)))
    assert dt2.hour == 13 and dt2.minute == 0
    assert row2["open"] == 20.0

def test_resample_higher_periods_week_month_year(engine):
    """
    测试从日K (1d) 动态合成周K (1w)、月K (1M) 和年K (1Y) 的聚合正确性：
    1. 1w (周K): 正确识别同一周内的交易日，开盘为周一/周二，收盘为周五，高低聚合，成交量求和；
    2. 1M (月K): 正确识别跨月日K，合成为月度K线；
    3. 1Y (年K): 正确跨年聚合为年度K线。
    """
    timestamps = [
        1704182400000, # 2024-01-02 (周二, Week 1)
        1704268800000, # 2024-01-03 (周三, Week 1)
        1704441600000, # 2024-01-05 (周五, Week 1)
        1704787200000, # 2024-01-09 (周二, Week 2)
        1707120000000, # 2024-02-05 (周一, Month 2)
        1736150400000, # 2025-01-06 (周一, Year 2025)
    ]
    df_daily = pl.DataFrame({
        "timestamp": timestamps,
        "open": [10.0, 10.2, 10.5, 11.0, 12.0, 20.0],
        "high": [10.6, 10.8, 10.9, 11.5, 12.8, 22.0],
        "low": [9.8, 10.0, 10.2, 10.8, 11.5, 19.0],
        "close": [10.4, 10.7, 10.3, 11.2, 12.5, 21.0],
        "volume": [100.0, 120.0, 150.0, 200.0, 300.0, 500.0],
        "amount": [1000.0, 1200.0, 1500.0, 2200.0, 3600.0, 10000.0],
        "factor": [1.0, 1.0, 1.0, 1.05, 1.10, 1.25],
        "nav": [None, None, None, None, None, None]
    })

    # 1. 测试周K (1w)
    df_1w = engine.resample_higher_period(df_daily, KlinePeriod.W1)
    assert len(df_1w) == 4
    w1 = df_1w.row(0, named=True)
    assert w1["timestamp"] == timestamps[0]
    assert w1["open"] == 10.0
    assert w1["high"] == 10.9
    assert w1["low"] == 9.8
    assert w1["close"] == 10.3
    assert w1["volume"] == 370.0
    assert w1["amount"] == 3700.0
    assert w1["factor"] == 1.0

    # 2. 测试月K (1M)
    df_1m = engine.resample_higher_period(df_daily, KlinePeriod.MON1)
    assert len(df_1m) == 3
    m1 = df_1m.row(0, named=True)
    assert m1["open"] == 10.0
    assert m1["high"] == 11.5
    assert m1["low"] == 9.8
    assert m1["close"] == 11.2
    assert m1["volume"] == 570.0
    assert m1["factor"] == 1.05

    # 3. 测试年K (1Y)
    df_1y = engine.resample_higher_period(df_daily, KlinePeriod.Y1)
    assert len(df_1y) == 2
    y1 = df_1y.row(0, named=True)
    assert y1["open"] == 10.0
    assert y1["high"] == 12.8
    assert y1["low"] == 9.8
    assert y1["close"] == 12.5
    assert y1["volume"] == 870.0
    assert y1["factor"] == 1.10

    y2 = df_1y.row(1, named=True)
    assert y2["open"] == 20.0
    assert y2["close"] == 21.0
    assert y2["volume"] == 500.0
    assert y2["factor"] == 1.25

