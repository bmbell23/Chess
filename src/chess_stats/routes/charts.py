"""Read-only chart data endpoints. All queries are scoped to the configured player."""
from collections import defaultdict
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from ..config import get_settings
from ..database import SessionLocal
from ..models import Game, Player
from ..services.sync import normalize_username

router = APIRouter(prefix="/api/v1/charts", tags=["charts"])

MODES = ("rapid", "blitz", "bullet", "daily")
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def _player_id(db, username: str | None = None) -> int:
    player = db.execute(
        select(Player).where(Player.username == normalize_username(username))
    ).scalar_one_or_none()
    if player is None:
        raise HTTPException(404, "player not synced yet")
    return player.id


@router.get("/rating-history")
def rating_history(player: str | None = None) -> dict:
    """Per-mode series of (game end time, post-game rating), chronological."""
    with SessionLocal() as db:
        pid = _player_id(db, player)
        rows = db.execute(
            select(Game.time_class, Game.end_time, Game.my_rating)
            .where(Game.player_id == pid, Game.my_rating.is_not(None))
            .order_by(Game.end_time)
        ).all()
    series: dict[str, list] = {m: [] for m in MODES}
    for time_class, end_time, rating in rows:
        if time_class in series:
            series[time_class].append({"t": end_time.isoformat(), "r": rating})
    return series


@router.get("/wld")
def win_loss_draw(player: str | None = None) -> dict:
    """W/L/D by mode, by color, and by month."""
    with SessionLocal() as db:
        pid = _player_id(db, player)
        rows = db.execute(
            select(Game.time_class, Game.color, Game.end_time, Game.result).where(
                Game.player_id == pid
            )
        ).all()
    by_mode = {m: {"win": 0, "loss": 0, "draw": 0} for m in MODES}
    by_color = {c: {"win": 0, "loss": 0, "draw": 0} for c in ("white", "black")}
    by_month: dict[str, dict] = defaultdict(lambda: {"win": 0, "loss": 0, "draw": 0})
    for time_class, color, end_time, result in rows:
        if time_class in by_mode:
            by_mode[time_class][result] += 1
        by_color[color][result] += 1
        by_month[end_time.strftime("%Y-%m")][result] += 1
    return {
        "by_mode": by_mode,
        "by_color": by_color,
        "by_month": dict(sorted(by_month.items())),
    }


@router.get("/openings")
def openings(limit: int = 10, min_games: int = 3, player: str | None = None) -> list[dict]:
    """Most-played openings with W/L/D and win rate."""
    with SessionLocal() as db:
        pid = _player_id(db, player)
        rows = db.execute(
            select(Game.eco, Game.opening_name, Game.result).where(
                Game.player_id == pid, Game.eco.is_not(None)
            )
        ).all()
    agg: dict[str, dict] = {}
    for eco, name, result in rows:
        entry = agg.setdefault(
            eco, {"eco": eco, "name": name, "win": 0, "loss": 0, "draw": 0}
        )
        entry[result] += 1
    out = []
    for entry in agg.values():
        games = entry["win"] + entry["loss"] + entry["draw"]
        if games < min_games:
            continue
        entry["games"] = games
        entry["winrate"] = round(100 * entry["win"] / games, 1)
        out.append(entry)
    out.sort(key=lambda e: e["games"], reverse=True)
    return out[:limit]


@router.get("/time-buckets")
def time_buckets(player: str | None = None) -> dict:
    """Win rate by local hour-of-day and day-of-week (games stored UTC)."""
    settings = get_settings()
    tz = ZoneInfo(settings.tz)
    utc = ZoneInfo("UTC")
    with SessionLocal() as db:
        pid = _player_id(db, player)
        rows = db.execute(
            select(Game.end_time, Game.result).where(Game.player_id == pid)
        ).all()
    hours = [{"games": 0, "win": 0} for _ in range(24)]
    days = [{"games": 0, "win": 0} for _ in range(7)]
    for end_time, result in rows:
        local = end_time.replace(tzinfo=utc).astimezone(tz)
        for bucket in (hours[local.hour], days[local.weekday()]):
            bucket["games"] += 1
            bucket["win"] += result == "win"
    def rate(b):
        return round(100 * b["win"] / b["games"], 1) if b["games"] else None
    return {
        "tz": settings.tz,
        "hours": [
            {"hour": h, "games": b["games"], "winrate": rate(b)}
            for h, b in enumerate(hours)
        ],
        "weekdays": [
            {"day": WEEKDAYS[i], "games": b["games"], "winrate": rate(b)}
            for i, b in enumerate(days)
        ],
    }
