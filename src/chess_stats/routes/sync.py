import logging
import threading

from fastapi import APIRouter, HTTPException

from ..services.chesscom_client import PlayerNotFound
from ..services.sync import SYNC_PROGRESS, SyncService, normalize_username, sync_status

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/sync", tags=["sync"])


def _run_sync(username: str) -> dict:
    service = SyncService()
    try:
        return service.run_full_sync(username)
    finally:
        service.client.close()


@router.post("")
def trigger_sync(player: str | None = None, background: bool = False) -> dict:
    """Sync a player. Synchronous by default (Sync now button); background=true
    spawns a worker and returns immediately (search flow polls /progress)."""
    username = normalize_username(player)
    if SYNC_PROGRESS.get(username, {}).get("state") == "running":
        return {"started": False, "reason": "already running", "player": username}
    if background:
        threading.Thread(
            target=lambda: _try_bg(username), name=f"sync-{username}", daemon=True
        ).start()
        return {"started": True, "player": username}
    try:
        return _run_sync(username)
    except PlayerNotFound:
        raise HTTPException(404, f"chess.com user '{username}' not found")


def _try_bg(username: str) -> None:
    try:
        _run_sync(username)
    except Exception as exc:  # progress dict already carries the error state
        logger.warning("background sync for %s failed: %s", username, exc)


@router.get("/progress")
def progress(player: str | None = None) -> dict:
    username = normalize_username(player)
    return {"player": username, **SYNC_PROGRESS.get(username, {"state": "idle"})}


@router.get("/status")
def status(player: str | None = None) -> dict:
    return sync_status(player)
