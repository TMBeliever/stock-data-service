from typing import List, Dict, Any
from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel
import asyncio
import akshare as ak
from collections import OrderedDict
import time
from core.models import format_symbol, Market, AssetType

router = APIRouter(prefix="/api/v1/stock", tags=["Analyst Consensus"])

class FinancialCache:
    """带 TTL (15分钟) 与容量上限 (50条) 的安全内存缓存"""
    def __init__(self, max_size: int = 50, ttl_seconds: int = 900):
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self._data: OrderedDict[str, Dict[str, Any]] = OrderedDict()

    def get(self, key: str) -> Dict[str, Any]:
        if key not in self._data:
            return None
        expire_time, val = self._data[key]
        if time.time() > expire_time:
            del self._data[key]
            return None
        self._data.move_to_end(key)
        return val

    def set(self, key: str, val: Dict[str, Any]):
        if key in self._data:
            del self._data[key]
        elif len(self._data) >= self.max_size:
            self._data.popitem(last=False)
        self._data[key] = (time.time() + self.ttl_seconds, val)

class EPSForecast(BaseModel):
    year: int
    eps: float

class AnalystConsensusResponse(BaseModel):
    symbol: str
    data_source: str
    report_count: int
    rating_buy: int
    rating_accumulate: int
    rating_neutral: int
    rating_reduce: int
    rating_sell: int
    eps_forecasts: List[EPSForecast]

_analyst_cache = FinancialCache(max_size=50, ttl_seconds=900)

@router.get("/analyst-consensus", response_model=AnalystConsensusResponse)
async def get_analyst_consensus(
    symbol: str = Query(..., description="股票代码 (如 600519, 000001)"),
    market: str = Query(..., description="市场标识 (仅支持 SH/SZ)")
):
    """
    获取个股分析师一致预期数据: 研报数量、评级分布、未来 EPS 预测。
    仅支持 A 股 (SH/SZ 市场)。
    """
    if market not in ["SH", "SZ"]:
        raise HTTPException(
            status_code=400,
            detail="Analyst consensus data only available for A-share (SH/SZ) symbols"
        )

    cache_key = f"analyst_{symbol}_{market}"
    cached = _analyst_cache.get(cache_key)
    if cached:
        return cached

    def _fetch():
        df = ak.stock_profit_forecast_em()
        row = df[df['代码'] == symbol]
        if row.empty:
            return None
        return row.iloc[0]

    row = await asyncio.to_thread(_fetch)

    if row is None:
        raise HTTPException(
            status_code=404,
            detail=f"No analyst consensus found for {symbol}"
        )

    report_count = int(row['研报数']) if row['研报数'] and row['研报数'] == row['研报数'] else 0

    rating_buy = int(row.get('机构投资评级(近六个月)-买入', 0) or 0)
    rating_accumulate = int(row.get('机构投资评级(近六个月)-增持', 0) or 0)
    rating_neutral = int(row.get('机构投资评级(近六个月)-中性', 0) or 0)
    rating_reduce = int(row.get('机构投资评级(近六个月)-减持', 0) or 0)
    rating_sell = int(row.get('机构投资评级(近六个月)-卖出', 0) or 0)

    eps_forecasts = []
    for year_col in ['2025预测每股收益', '2026预测每股收益', '2027预测每股收益', '2028预测每股收益']:
        if year_col in row.index:
            year = int(year_col[:4])
            eps = row[year_col]
            if eps and eps == eps:
                eps_forecasts.append(EPSForecast(year=year, eps=float(eps)))

    # Format symbol as full format (e.g., "600519.SH.STK")
    formatted_symbol = format_symbol(symbol, market, AssetType.STOCK)

    result = AnalystConsensusResponse(
        symbol=formatted_symbol,
        data_source="东方财富 (East Money)",
        report_count=report_count,
        rating_buy=rating_buy,
        rating_accumulate=rating_accumulate,
        rating_neutral=rating_neutral,
        rating_reduce=rating_reduce,
        rating_sell=rating_sell,
        eps_forecasts=eps_forecasts
    )

    _analyst_cache.set(cache_key, result)
    return result
