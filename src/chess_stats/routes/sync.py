from fastapi import APIRouter

from ..services.sync import SyncService, sync_status

router = APIRouter(prefix="/api/v1/sync", tags=["sync"])


@router.post("")
def trigger_sync() -> dict:
    # sync def endpoint → FastAPI runs it in the threadpool; the client's
    # internal lock keeps chess.com access serial even if triggered twice
    service = SyncService()
    try:
        return service.run_full_sync()
    finally:
        service.client.close()


@router.get("/status")
def status() -> dict:
    return sync_status()
