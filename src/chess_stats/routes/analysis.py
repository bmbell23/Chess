import logging
import threading

from fastapi import APIRouter, HTTPException

from ..services.analysis import ANALYSIS_PROGRESS, engine_available, run_analysis
from ..services.sync import normalize_username

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/analysis", tags=["analysis"])


@router.post("")
def trigger_analysis(player: str | None = None, background: bool = True) -> dict:
    username = normalize_username(player)
    if not engine_available():
        raise HTTPException(503, "stockfish not installed in this environment")
    if ANALYSIS_PROGRESS.get(username, {}).get("state") == "running":
        return {"started": False, "reason": "already running", "player": username}
    if background:
        threading.Thread(
            target=lambda: _bg(username), name=f"analysis-{username}", daemon=True
        ).start()
        return {"started": True, "player": username}
    return run_analysis(username)


def _bg(username: str) -> None:
    try:
        run_analysis(username)
    except Exception as exc:
        logger.warning("analysis for %s failed: %s", username, exc)


@router.get("/progress")
def progress(player: str | None = None) -> dict:
    username = normalize_username(player)
    return {"player": username, **ANALYSIS_PROGRESS.get(username, {"state": "idle"})}
