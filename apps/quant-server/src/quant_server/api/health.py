from fastapi import APIRouter
from quant_core.client.data_client import data_client

router = APIRouter()

@router.get("/health")
def health_check():
    data_ok = data_client.check_health()
    return {
        "status": "ok",
        "service": "quant-server",
        "data_service_connected": data_ok
    }
