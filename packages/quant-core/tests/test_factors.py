import pytest
from quant_core.factors import (
    sma, ema, rsi, macd, bollinger_bands, atr,
    roc, momentum, percentile_rank, zscore
)

def test_technical_factors():
    prices = [10.0, 11.0, 12.0, 13.0, 14.0, 15.0]
    assert sma(prices, 3) == pytest.approx(14.0)
    assert ema(prices, 3) > 13.0

    # RSI on rising prices
    r = rsi(prices, period=3)
    assert r > 80.0

    # Bollinger Bands
    upper, mid, lower = bollinger_bands(prices, period=5)
    assert upper > mid > lower

    # ATR
    h = [11.0, 12.0, 13.0, 14.0, 15.0]
    l = [9.0, 10.0, 11.0, 12.0, 13.0]
    c = [10.0, 11.0, 12.0, 13.0, 14.0]
    a = atr(h, l, c, period=3)
    assert a > 0

def test_momentum_and_value_factors():
    prices = [10.0, 12.0, 15.0]
    assert roc(prices, period=2) == pytest.approx(0.5)
    assert momentum(prices, period=2) == pytest.approx(5.0)

    history = [10.0, 20.0, 30.0, 40.0, 50.0]
    assert percentile_rank(30.0, history) == pytest.approx(0.5)
    assert zscore(30.0, history) == pytest.approx(0.0)
