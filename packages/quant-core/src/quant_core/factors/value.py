from typing import Sequence, Dict, Any, Optional
import numpy as np
import polars as pl
import pandas as pd

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

def calculate_valuation_metrics(
    history_values: Sequence[float],
    current_val: Optional[float] = None
) -> Dict[str, float]:
    """
    计算估值因子的全量分位指标：
    - min / max / mean / median
    - 危险度 (Z-Score)
    - 历史分位点 (Percentile: 0.0 ~ 1.0)
    - 低估阈值 (20% 分位)、中枢 (50% 分位)、高估阈值 (80% 分位)
    """
    vals = [float(v) for v in history_values if v is not None and not np.isnan(v)]
    if not vals:
        return {
            "current": 0.0, "percentile": 0.5, "zscore": 0.0,
            "min": 0.0, "max": 0.0, "median": 0.0, "p20": 0.0, "p50": 0.0, "p80": 0.0
        }
    
    cur = current_val if current_val is not None else vals[-1]
    p_rank = percentile_rank(cur, vals)
    z = zscore(cur, vals)
    
    return {
        "current": round(float(cur), 4),
        "percentile": round(p_rank, 4),
        "zscore": round(z, 3),
        "min": round(float(np.min(vals)), 4),
        "max": round(float(np.max(vals)), 4),
        "mean": round(float(np.mean(vals)), 4),
        "median": round(float(np.median(vals)), 4),
        "p20": round(float(np.percentile(vals, 20)), 4),
        "p50": round(float(np.percentile(vals, 50)), 4),
        "p80": round(float(np.percentile(vals, 80)), 4),
    }

