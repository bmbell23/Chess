from fastapi import APIRouter

from ..services.achievements import evaluate

router = APIRouter(prefix="/api/v1", tags=["achievements"])


@router.get("/achievements")
def achievements(player: str | None = None) -> dict:
    return evaluate(player)
