from fastapi import APIRouter
from typing import List, Dict, Any

router = APIRouter()

@router.get("/strategies")
def list_available_strategies() -> List[Dict[str, Any]]:
    """返回内核中内置的标准 Benchmark 策略列表与参数说明"""
    return [
        {
            "id": "ma",
            "name": "双均线趋势策略 (Dual Moving Average)",
            "description": "短期均线上穿长期均线金叉开仓，下穿死叉平仓",
            "default_params": {
                "fast_period": 5,
                "slow_period": 20
            }
        },
        {
            "id": "dividend",
            "name": "红利ETF分位数调仓策略 (Dividend ETF Rebalance)",
            "description": "按价格历史分位数动态逆向定投与调仓 (极度低估加仓，高估主动止盈)",
            "default_params": {
                "window": 120
            }
        }
    ]
