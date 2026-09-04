from typing import List
from fastapi import APIRouter, Query, HTTPException
from core.models import SnapshotBatchRequest, SnapshotBatchResponse
from adapters.snapshot import snapshot_adapter

router = APIRouter(prefix="/api/v1/snapshot", tags=["Real-time Batch Market Snapshot"])

MAX_BATCH_SYMBOLS = 200

@router.get("", response_model=SnapshotBatchResponse)
async def get_snapshots_get(
    symbols: str = Query(..., description="逗号分隔的标的代码列表，如 600519.SH.STK,AAPL.US.STK,0700.HK.STK,510300.SH.ETF")
):
    """
    【批量实时股票行情快照】GET 方式：
    支持跨市场 (A股/港股/美股/ETF/指数) 一次性获取多只股票的最新快照 (最新价、涨跌幅、成交量额、最高最低等)。
    单次最多支持 200 只股票。
    严格遵循真实性原则: 若标的无实时行情或代码无效，记录于 missing 列表，严禁伪造假数据。
    """
    sym_list = [s.strip() for s in symbols.split(",") if s.strip()]
    if not sym_list:
        raise HTTPException(status_code=400, detail="Symbols parameter cannot be empty.")
    if len(sym_list) > MAX_BATCH_SYMBOLS:
        raise HTTPException(
            status_code=400,
            detail=f"Batch size ({len(sym_list)}) exceeds maximum limit of {MAX_BATCH_SYMBOLS} symbols."
        )

    snapshots, missing = await snapshot_adapter.fetch_snapshots(sym_list)
    return SnapshotBatchResponse(
        count=len(snapshots),
        data=snapshots,
        missing=missing
    )

@router.post("/batch", response_model=SnapshotBatchResponse)
async def get_snapshots_batch(
    request: SnapshotBatchRequest
):
    """
    【批量实时股票行情快照】POST 方式：
    接收 JSON 请求体 {"symbols": ["600519.SH.STK", "AAPL.US.STK", ...]}，
    适合自选股列表、持仓看板、组合跟踪等大批量标的一次性拉取。
    单次最多支持 200 只股票。
    严格遵循真实性原则: 若标的无实时行情或代码无效，记录于 missing 列表，严禁伪造假数据。
    """
    sym_list = [s.strip() for s in request.symbols if s.strip()]
    if not sym_list:
        raise HTTPException(status_code=400, detail="Symbols list cannot be empty.")
    if len(sym_list) > MAX_BATCH_SYMBOLS:
        raise HTTPException(
            status_code=400,
            detail=f"Batch size ({len(sym_list)}) exceeds maximum limit of {MAX_BATCH_SYMBOLS} symbols."
        )

    snapshots, missing = await snapshot_adapter.fetch_snapshots(sym_list)
    return SnapshotBatchResponse(
        count=len(snapshots),
        data=snapshots,
        missing=missing
    )
