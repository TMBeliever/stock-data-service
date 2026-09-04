from typing import Sequence

def roc(prices: Sequence[float], period: int = 12) -> float:
    """变动率指标 (Rate of Change, 收益率百分比)"""
    if len(prices) <= period or prices[-period-1] == 0:
        return 0.0
    return (prices[-1] - prices[-period-1]) / prices[-period-1]

def momentum(prices: Sequence[float], period: int = 10) -> float:
    """动量指标 (绝对价格变动)"""
    if len(prices) <= period:
        return 0.0
    return prices[-1] - prices[-period-1]
