from typing import Sequence, Tuple
import numpy as np

def sma(prices: Sequence[float], period: int) -> float:
    """简单移动平均 (Simple Moving Average)"""
    if len(prices) < period or period <= 0:
        return 0.0
    return float(np.mean(prices[-period:]))

def ema(prices: Sequence[float], period: int) -> float:
    """指数移动平均 (Exponential Moving Average)"""
    if len(prices) < period or period <= 0:
        return 0.0
    alpha = 2.0 / (period + 1.0)
    res = prices[0]
    for p in prices[1:]:
        res = alpha * p + (1.0 - alpha) * res
    return float(res)

def rsi(prices: Sequence[float], period: int = 14) -> float:
    """相对强弱指标 (Relative Strength Index, 0~100)"""
    if len(prices) <= period:
        return 50.0
    diffs = np.diff(prices[-period-1:])
    gains = diffs[diffs > 0]
    losses = -diffs[diffs < 0]
    
    avg_gain = float(np.mean(gains)) if len(gains) > 0 else 0.0
    avg_loss = float(np.mean(losses)) if len(losses) > 0 else 0.0
    
    if avg_loss == 0.0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return float(100.0 - (100.0 / (1.0 + rs)))

def macd(
    prices: Sequence[float],
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9
) -> Tuple[float, float, float]:
    """MACD 指标: 返回 (DIF, DEA, MACD柱)"""
    if len(prices) < slow_period + signal_period:
        return 0.0, 0.0, 0.0
    
    # 计算序列 EMA
    def calc_ema_series(data: Sequence[float], n: int) -> list[float]:
        alpha = 2.0 / (n + 1.0)
        res = [data[0]]
        for v in data[1:]:
            res.append(alpha * v + (1.0 - alpha) * res[-1])
        return res

    fast_ema = calc_ema_series(prices, fast_period)
    slow_ema = calc_ema_series(prices, slow_period)
    dif_series = [f - s for f, s in zip(fast_ema, slow_ema)]
    
    dea_series = calc_ema_series(dif_series[-signal_period*2:], signal_period)
    dif = dif_series[-1]
    dea = dea_series[-1]
    hist = (dif - dea) * 2.0
    return float(dif), float(dea), float(hist)

def bollinger_bands(
    prices: Sequence[float],
    period: int = 20,
    num_std: float = 2.0
) -> Tuple[float, float, float]:
    """布林带 (Bollinger Bands): 返回 (上轨, 中轨, 下轨)"""
    if len(prices) < period:
        return 0.0, 0.0, 0.0
    window = prices[-period:]
    mid = float(np.mean(window))
    std = float(np.std(window))
    upper = mid + num_std * std
    lower = mid - num_std * std
    return upper, mid, lower

def atr(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    period: int = 14
) -> float:
    """真实波幅均值 (Average True Range)"""
    if len(closes) < period + 1:
        return 0.0
    tr_list = []
    for i in range(-period, 0):
        h = highs[i]
        l = lows[i]
        prev_c = closes[i-1]
        tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
        tr_list.append(tr)
    return float(np.mean(tr_list))
