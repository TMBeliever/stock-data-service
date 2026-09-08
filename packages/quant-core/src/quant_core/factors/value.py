from typing import Sequence, Dict, Any, Optional
import numpy as np
import polars as pl
import pandas as pd

def percentile_rank(val: float, history: Sequence[float]) -> float:
    """计算某个数值在历史序列中的标准分位数 (中点经验累积分布: 0.0 ~ 1.0)"""
    vals = [v for v in history if v is not None and not np.isnan(v)]
    if not vals:
        return 0.5
    less_count = sum(1 for v in vals if v < val)
    equal_count = sum(1 for v in vals if v == val)
    return float((less_count + 0.5 * equal_count) / len(vals))


def min_max_position(val: float, history: Sequence[float]) -> float:
    """计算数值在历史极值波幅中的相对线性位置 (0.0 ~ 1.0)"""
    vals = [v for v in history if v is not None and not np.isnan(v)]
    if not vals:
        return 0.5
    min_v = min(vals)
    max_v = max(vals)
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
    mm_pos = min_max_position(cur, vals)
    z = zscore(cur, vals)
    
    return {
        "current": round(float(cur), 4),
        "percentile": round(p_rank, 4),
        "min_max_ratio": round(mm_pos, 4),
        "zscore": round(z, 3),
        "min": round(float(np.min(vals)), 4),
        "max": round(float(np.max(vals)), 4),
        "mean": round(float(np.mean(vals)), 4),
        "median": round(float(np.median(vals)), 4),
        "p20": round(float(np.percentile(vals, 20)), 4),
        "p50": round(float(np.percentile(vals, 50)), 4),
        "p80": round(float(np.percentile(vals, 80)), 4),
    }


