from typing import Sequence
import numpy as np

def percentile_rank(val: float, history: Sequence[float]) -> float:
    """计算某个数值在历史序列中的分位数 (0.0 ~ 1.0)"""
    if not history:
        return 0.5
    min_v = min(history)
    max_v = max(history)
    if max_v == min_v:
        return 0.5
    return float(np.clip((val - min_v) / (max_v - min_v), 0.0, 1.0))

def zscore(val: float, history: Sequence[float]) -> float:
    """Z-Score 标准化得分"""
    if len(history) < 2:
        return 0.0
    mean = float(np.mean(history))
    std = float(np.std(history))
    if std < 1e-8:
        return 0.0
    return float((val - mean) / std)
