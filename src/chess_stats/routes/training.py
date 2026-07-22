from fastapi import APIRouter

from ..services.chesscom_web import training_stats
from ..services.sync import normalize_username

router = APIRouter(prefix="/api/v1", tags=["training"])


@router.get("/training")
def training(player: str | None = None) -> dict:
    return {"player": normalize_username(player), **training_stats(normalize_username(player))}
