from typing import Optional, List
from fastapi import APIRouter, Query, HTTPException
from core.models import Market, AssetType, SymbolInfo
from core.database import meta_db

router = APIRouter(prefix="/api/v1/meta", tags=["Metadata"])

@router.get("/symbols", response_model=List[dict])
async def list_symbols(
    market: Optional[Market] = Query(None, description="市场: SH, SZ, US, HK"),
    asset_type: Optional[AssetType] = Query(None, description="资产类别: STK, IDX, ETF"),
    is_benchmark: Optional[bool] = Query(None, description="是否基准资产")
):
    m_str = market.value if market else None
    t_str = asset_type.value if asset_type else None
    return meta_db.list_symbols(market=m_str, asset_type=t_str, is_benchmark=is_benchmark)

@router.get("/calendar", response_model=dict)
async def check_trading_day(
    market: Market = Query(..., description="市场"),
    trade_date: str = Query(..., description="日期: YYYY-MM-DD")
):
    status = meta_db.get_calendar_status(market.value, trade_date)
    is_open = meta_db.is_trading_day(market.value, trade_date)
    return {
        "market": market.value,
        "trade_date": trade_date,
        "status": status,
        "is_open": is_open
    }
