from fastapi import APIRouter
from storage.sentinel import sentinel

router = APIRouter(prefix="/api/v1/system", tags=["System"])

@router.get("/storage", response_model=dict)
async def get_storage_status():
    """获取 50GB 磁盘空间与缓存水位状态"""
    return sentinel.get_storage_stats()

@router.post("/evict", response_model=dict)
async def trigger_eviction():
    """手动触发 LRU 淘汰清理"""
    freed_bytes = sentinel.check_and_evict()
    return {
        "freed_bytes": freed_bytes,
        "freed_mb": round(freed_bytes / (1024 ** 2), 2),
        "status": "success"
    }
